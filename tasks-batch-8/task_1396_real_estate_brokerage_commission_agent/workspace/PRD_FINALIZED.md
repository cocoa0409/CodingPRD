# Real Estate Brokerage Commission API — Product Requirements Document

## 1. Introduction

A franchise real estate brokerage runs on commission math that looks simple from the outside and is anything but. Every closed deal splits its gross commission between the producing agent and the company along a tiered schedule that improves as the agent's production year accrues; the franchise takes a royalty off every dollar until an annual cap is reached; errors-and-omissions insurance and desk fees come out of each check; co-broke brokerages and referring agents are paid before anyone else; team leads and mentors carve their overrides out of the agent's share. All of this money moves through a trust account that regulators expect to reconcile to the cent, and every agent is an independent contractor whose year-end 1099 must reflect what was actually paid, not what was merely earned.

This document specifies the API that runs that back office. All endpoints are mounted under the `/brokerage` prefix. The system tracks agents and their commission plans, effective-dated plan enrollments, anniversary-year accrual windows with company-dollar and royalty caps, the deal pipeline from draft to closing, a nine-step settlement waterfall that posts an immutable accounting of every split, a four-eyes disbursement process over trust funds, an agent debit ledger for fee shortfalls and their recovery, and 1099 generation on both cash and accrual bases. A logical clock drives all calendar behavior — enrollment activations, anniversary book-closing, closing-date validation, and tax-year bounds — so that every temporal rule in this document is deterministic and testable.

## 2. Global Specifications & System-Wide Principles

This section defines the rules that hold for every endpoint in the API: who may call what, how responses are shaped, how time and money are represented, and the order in which the server guards a request.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the capacity in which they act. A request missing either header, or carrying an empty value in either, is rejected with `ERR_MISSING_USER_CONTEXT` (HTTP 400). The system recognizes five roles, spelled exactly as follows: `BrokerAdmin`, `OfficeManager`, `TransactionCoordinator`, `Agent`, and `Auditor`. Each endpoint declares the roles admitted to it (see §4); a caller whose role is not on an endpoint's list is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403).

- A `BrokerAdmin` is the broker of record and market-center operator: this role owns commission plans, enrollments, the agent lifecycle, manual debit adjustments, 1099 forms, and the logical clock, and may additionally authorize, release, and void disbursement legs subject to the segregation-of-duties rules in §2.8.
- An `OfficeManager` is the disbursement officer: this role authorizes, releases, and voids disbursement legs, and cannot post settlements or manage plans and agents.
- A `TransactionCoordinator` staffs the deal desk: this role creates and edits deals for any agent, drives the deal pipeline, records closings, and posts and reverses settlements. The coordinator who posts a settlement is recorded on it, and for segregation-of-duties purposes can never authorize that settlement's legs.
- An `Agent` is an independent-contractor agent: this role manages its own deal drafts and pipeline submissions and enjoys read-only access to its own financial records — deals, settlements, legs payable to it, ledger entries, anniversary periods, tax forms, and enrollments.
- An `Auditor` is a read-only compliance auditor with access to every read endpoint, including the global trust ledger, and no write access at all.

Identity binding works as follows. When `X-User-Role` is `Agent`, `X-User-ID` is the `id` of the acting Agent; ownership checks on any resource that references an Agent compare the resource's foreign-key field to `X-User-ID`, and a caller touching a resource owned by another agent is rejected with `ERR_FORBIDDEN_RESOURCE` (HTTP 403). A request arriving with `X-User-Role` set to `Agent` whose `X-User-ID` does not identify an existing Agent is rejected with `ERR_UNKNOWN_USER_IDENTITY` (HTTP 403). When `X-User-Role` is `BrokerAdmin`, `OfficeManager`, `TransactionCoordinator`, or `Auditor`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it — for example as `posted_by_user_id` on a settlement, or as `authorized_by_user_id` and `released_by_user_id` on a disbursement leg — but does not compare it to any entity's `id`.

### 2.2. API Response Structure

#### Standard Success Response Format

All successful API responses (those with 2xx status codes) follow this standard envelope format in their JSON body:

```json
{
  "meta": {
    "api_request_id": "req_RANDOMALPHANUM123456",
    "api_request_timestamp": "2025-05-24T10:30:00.123Z",
    "limit": 10,
    "offset": 0,
    "total_count": 100,
    "has_more": true
  },
  "response_type": "object" | "array",
  "data": { }
}
```

- The `api_request_id` is a server-generated unique identifier for the request that starts with `req_`.
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits.
- The `response_type` is either "object" for a single resource or "array" for a list of resources.
- The `data` field contains the resource object or an array of resource objects. For 2xx responses with no data, it contains an empty object. Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field.
- Pagination-related fields in `meta` (`limit`, `offset`, `total_count`, `has_more`) are included for list endpoints.

#### Standard Error Response Format

All error API responses (4xx status codes) follow this standard envelope format:

```json
{
  "meta": {
    "api_request_id": "req_RANDOMALPHANUM123456",
    "api_request_timestamp": "2025-05-24T10:30:00.123Z"
  },
  "response_type": "error",
  "data": {
    "error_id": "UNIQUE_ERROR_IDENTIFIER_STRING",
    "message": "A human-readable explanation of the error."
  }
}
```

- The `meta` object for error responses contains only `api_request_id` and `api_request_timestamp`.
- The `error_id` is a unique, machine-readable string that identifies the specific error.
- The `message` provides a human-readable explanation of what went wrong.

---

### 2.3. Pagination

List endpoints accept the query parameters `limit` and `offset`. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter says how many items to skip and defaults to 0. Unless a list's own section states otherwise, list endpoints return resources sorted by `created_at` in ascending order. Paginated list responses carry the fields `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. The Logical Clock and the Brokerage Calendar

Date-typed fields are ISO calendar dates in `YYYY-MM-DD` form; timestamp fields are ISO 8601 UTC datetimes. The system runs on a logical clock rather than wall-clock time: at startup the clock reads exactly 2026-08-01T00:00:00Z and must never fall back to wall-clock time. The **clock date** — the UTC calendar date of the current clock instant — is the date against which enrollment activations, anniversary-window closures, closing-date validation, termination dating, and tax-year bounds are all evaluated.

A BrokerAdmin-only, test-driving capability advances the logical clock to a supplied `to_iso8601` instant. The clock moves forward only: a `to_iso8601` that is not strictly later than the current clock instant is rejected with `ERR_CLOCK_REGRESSION` (HTTP 422). Advancing the clock runs the system sweep described in §3.3 and §3.4 — scheduled enrollments whose effective date has been reached activate, anniversary windows are materialized, and windows whose end has passed close — and the response reports `current_utc`, the list `activated_enrollment_ids`, and the list `closed_window_ids`.

### 2.5. Common Resource Properties

Every primary resource — agents, commission plans, enrollments, anniversary periods, deals, settlements, disbursement legs, and tax forms — carries a standard set of system-managed fields:

- `id` (string): a unique, server-generated identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was first created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording the last modification; it is refreshed on every change to the resource.
- `version` (integer): a system-managed integer starting at 1 that increments by exactly 1 on every mutation of the resource, including state transitions and cascade-driven changes.

Two resources are append-only ledger records and break this pattern: a debit ledger entry and a trust transaction each carry only `id` and `created_at` — both `updated_at` and `version` are absent from them, because they are never modified after creation.

### 2.6. Money, Cents, and the Per-Step Rounding Rule

All monetary amounts in the API are integer cents — never fractional, never floating-point dollars. All percentage or split fields are decimal fractions between 0 and 1 inclusive (for example, a six percent royalty is carried as 0.06) and preserve the precision supplied at input.

Rounding inside the settlement waterfall is pinned to a strict per-step discipline: every commission component is rounded half up to whole cents at its own waterfall step, before any later step consumes the value. Implementations must not carry fractional cents through the waterfall and round once at the end — per-step rounding followed by exact integer composition is the authoritative order and produces the authoritative leg amounts. A consequence of this rule is that the whole-cent figures stored on a posted settlement are, by construction, the exact figures that disbursement legs pay out.

### 2.7. Optimistic Concurrency Control

Exactly three write endpoints participate in optimistic concurrency control, and no other endpoint accepts a version field:

- A `POST /brokerage/agents/{agentId}/enrollments` request must carry `expected_agent_version`, holding the caller's last observed `version` of the agent. Because creating an enrollment supersedes the agent's current enrollment and advances the agent's version, a value that no longer matches the agent's current `version` means another write has moved the agent since the caller last read it; the create is then rejected with `ERR_STALE_AGENT_VERSION` (HTTP 412).
- A `PATCH /brokerage/agents/{agentId}` request must likewise carry `expected_agent_version`. When the caller's snapshot of the agent predates an intervening write — a suspension, an enrollment supersede, or another edit that may have changed the very mentor and team fields being edited — the mismatch is rejected with `ERR_STALE_AGENT_VERSION` (HTTP 412).
- A `PUT /brokerage/plans/{planId}` request must carry `expected_plan_version`. If an intervening edit has already advanced the plan's `version`, applying the caller's diff would silently discard that edit, so the request is rejected with `ERR_STALE_PLAN_VERSION` (HTTP 412).

### 2.8. Segregation of Duties Over Trust Funds

No single operator may both post a settlement and authorize its disbursements, and no single operator may both authorize and release the same disbursement. Concretely, authorizing a disbursement leg requires the caller's `X-User-ID` to differ from the settlement's `posted_by_user_id`, and releasing a leg requires the caller's `X-User-ID` to differ from that leg's `authorized_by_user_id`. Either violation is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). Since settlement posting belongs to the `TransactionCoordinator` while authorization and release belong to the `OfficeManager` and `BrokerAdmin`, at least two distinct operators touch every dollar that leaves the trust account.

### 2.9. Guard Evaluation Order

Every request passes through the same ordered gauntlet of validations, and the first failing guard determines the error returned — a request that would fail several checks always reports the earliest one. The order is:

1. Header presence: missing or empty `X-User-ID` or `X-User-Role` yields `ERR_MISSING_USER_CONTEXT`.
2. Role admission: the caller's role must appear in the endpoint's role list, else `ERR_FORBIDDEN_FOR_ROLE`.
3. Agent identity resolution: an `Agent`-role caller must identify an existing Agent, else `ERR_UNKNOWN_USER_IDENTITY`.
4. Agent ownership scoping: an `Agent`-role caller may touch only resources they own, else `ERR_FORBIDDEN_RESOURCE`.
5. Request schema: every required input field of the endpoint must be present and parse to its declared type, and every query filter — including enum-valued filters — must parse to its declared type, else `ERR_INVALID_REQUEST`.
6. Path existence: path identifiers must resolve, validated left to right, else `ERR_NOT_FOUND`.
7. Optimistic concurrency: any `expected_agent_version` or `expected_plan_version` on the request must equal the parent's current `version`, else `ERR_STALE_AGENT_VERSION` or `ERR_STALE_PLAN_VERSION`.
8. State validity: the target resource must be in a state that permits the operation — this family includes `ERR_AGENT_INVALID_STATE`, `ERR_PLAN_INVALID_STATE`, `ERR_PLAN_NOT_ACTIVE`, `ERR_DEAL_INVALID_STATE`, `ERR_DEAL_HAS_SETTLEMENT`, `ERR_LEG_INVALID_STATE`, `ERR_TAX_FORM_INVALID_STATE`, and `ERR_WINDOW_CLOSED`.
9. Segregation of duties: `ERR_SEGREGATION_OF_DUTIES`.
10. The join-date temporal rule: `ERR_DEAL_BEFORE_JOIN`.
11. The forward-only temporal rules: `ERR_FUTURE_CLOSING` and `ERR_CLOCK_REGRESSION`.
12. Enrollment effective-date chaining: `ERR_EFFECTIVE_DATE_REGRESSION` and `ERR_ENROLLMENT_ALREADY_SCHEDULED`.
13. Tax-year bounds: `ERR_TAX_YEAR_INVALID`.
14. Referential integrity of related parties: `ERR_NOT_FOUND`, `ERR_SELF_REFERENCE`, `ERR_REFERRAL_INCOMPLETE`, `ERR_COBROKE_PAYEE_MISSING`.
15. Referential state guards: `ERR_NO_PLAN_ENROLLMENT`, `ERR_PLAN_IN_USE`, `ERR_AGENT_HAS_OPEN_DEALS`, `ERR_LEGS_OUTSTANDING`.
16. Uniqueness: `ERR_LICENSE_NUMBER_TAKEN` and `ERR_TAX_FORM_FINALIZED_EXISTS`.
17. Fiscal range constraints, checked last: `ERR_NONPOSITIVE_GROSS`, `ERR_COBROKE_EXCEEDS_GROSS`, `ERR_PCT_OUT_OF_RANGE`, `ERR_PLAN_TIERS_INVALID`, `ERR_DEBIT_ADJUSTMENT_INVALID`, `ERR_WRITE_OFF_EXCEEDS_DEBIT`.

### 2.10. Path Resolution for Nested Addresses

Endpoints addressed by path identifiers validate those identifiers in a strict left-to-right order: `agentId` first, then `planId`, `dealId`, `settlementId`, `legId`, `taxFormId`, or `enrollmentId` as the path requires, then any trailing identifier. Standalone resources are addressed by their own identifiers — `periodId` for anniversary periods, `entryId` for ledger entries, and `transactionId` for trust transactions — under the same rule. The first identifier that does not correspond to an existing resource produces `ERR_NOT_FOUND` (HTTP 404), and identifiers to its right are never examined.

### 2.11. Conservation Invariants: Company Books, Debit Ledger, and Trust Account

Three reconciliation invariants hold at every instant and may be audited on read:

- **Leg conservation.** The disbursement legs created by a settlement always sum, to the cent, to the deal's `gross_commission_cents`.
- **Debit-ledger reconciliation.** An agent's `debit_balance_cents` always equals the sum of `amount_cents` over all of the agent's ledger entries, with the floor of zero enforced only at write time — a write-off may never exceed the balance. Each entry records `resulting_balance_cents`, the agent's balance immediately after that entry; entries are created one per mutation within a single request and read in `created_at` ascending order.
- **Trust conservation.** The global trust balance — the sum of `amount_cents` across every trust transaction ever recorded — is never negative. Per deal, `trust_received_cents` equals the sum of that deal's `RECEIPT` and any `RECEIPT_REVERSAL` amounts; while a deal is `SETTLED`, its settlement's non-`VOIDED` leg amounts sum to `trust_received_cents`, which equals the gross; once the deal reaches `DISBURSED`, its `RELEASE` transactions sum to the gross and the deal's net trust position returns to zero.

## 3. Business Logic & Workflows

### 3.1. Building the Roster: Agent Records and the Agent Lifecycle

A `BrokerAdmin` adds an agent to the roster by supplying the agent's `full_name`, `email`, `license_number`, and `joined_at`, plus the optional relationship fields `mentor_agent_id`, `team_lead_agent_id`, and `team_override_pct`. The `license_number` is the state license identifier and must be unique across all agents; a collision is rejected with `ERR_LICENSE_NUMBER_TAKEN` (HTTP 409). The `joined_at` date anchors the agent's anniversary windows forever and, together with `license_number`, is immutable after creation. Both `mentor_agent_id` and `team_lead_agent_id` default to null and, when supplied, must reference existing Agents (an unknown reference is rejected with `ERR_NOT_FOUND`) that differ from the agent being created or edited — pointing either field at the agent themself is rejected with `ERR_SELF_REFERENCE` (HTTP 422). The `team_override_pct` is the fraction of the agent's gross share paid to the team lead on each settled deal; it defaults to 0, must lie between 0 and 1 inclusive (violations are rejected with `ERR_PCT_OUT_OF_RANGE`, HTTP 422), and is ignored whenever `team_lead_agent_id` is null.

A newly created agent starts in `ONBOARDING` status with `debit_balance_cents` at 0 and `settled_deal_count` at 0. Activation by a `BrokerAdmin` moves the agent from `ONBOARDING` to `ACTIVE`; only `ACTIVE` agents may be credited with new deals, so deal creation by or for an agent in any other status is rejected with `ERR_AGENT_INVALID_STATE` (HTTP 409). Suspension moves an agent from `ACTIVE` to `SUSPENDED` — a suspended agent keeps their existing deal pipeline but cannot create new deals — and reinstatement returns them from `SUSPENDED` to `ACTIVE`. Each of these transitions requires the named source state: suspending an already-`SUSPENDED` agent or activating an already-`ACTIVE` one is rejected with `ERR_AGENT_INVALID_STATE`. Every lifecycle transition increments the agent's `version` by 1.

Termination is the terminal act of the lifecycle and is reachable from `ACTIVE`, `SUSPENDED`, or `ONBOARDING`, landing the agent in `TERMINATED`. It is blocked while the agent still has deals in `DRAFT` or `PENDING_CLOSING` — the rejection is `ERR_AGENT_HAS_OPEN_DEALS` (HTTP 409) — though for an `ONBOARDING` agent this guard is always satisfiable, since a non-`ACTIVE` agent could never have created deals. Termination cascades into the agent's enrollments: the agent's `ACTIVE` enrollment, if any, moves to `ENDED` with its `effective_to` set to the termination date (the clock date), and the agent's `SCHEDULED` enrollment, if any, moves to `CANCELLED` with its `effective_to` set to its own `effective_from`, a zero-length coverage interval.

A `BrokerAdmin` may also update an agent's mutable fields — `full_name`, `email`, `mentor_agent_id`, `team_lead_agent_id`, and `team_override_pct` — through a patch that must carry `expected_agent_version` under the optimistic-concurrency rule of §2.7; a successful patch increments the agent's `version` by 1. Two computed figures ride on every agent record: `debit_balance_cents`, the amount the agent owes the brokerage, which always equals the sum of the agent's ledger entries with a floor of zero (see §3.8), and `settled_deal_count`, the count of settlements currently `POSTED` for the agent, incremented at settle time and decremented at unsettle time, which drives mentor-split eligibility in §3.6. The roster listing supports the filters `status`, `mentor_agent_id`, and `team_lead_agent_id`; `Agent`-role callers listing agents see only themselves, and an agent record read includes `status`, `debit_balance_cents`, `settled_deal_count`, and `version`.

### 3.2. Commission Plans and the Tiered Company-Dollar Schedule

A commission plan is the contract between brokerage and agent, authored by a `BrokerAdmin` with a display `name` and the following economic terms: `royalty_pct`, the franchise royalty fraction taken from the adjusted commission; `royalty_cap_cents`, the maximum royalty an agent pays per anniversary window under the plan; `eo_fee_cents`, a flat errors-and-omissions insurance fee deducted per settled deal; `transaction_fee_cents`, a flat transaction or desk fee deducted per settled deal; `mentor_split_pct` (default 0), the fraction of the agent's gross share paid to their mentor during the agent's early production; `mentor_deal_count` (default 0), the number of an agent's settled deals — measured by `settled_deal_count` at settle time — to which the mentor split applies, where 0 disables the mentor split entirely; and `tiers`, the company-dollar schedule.

The `tiers` list is ordered, and each element pairs a `threshold_company_dollar_cents` with a `broker_split_pct`. A tier's threshold is the cumulative company-dollar accrual at which that tier ends, exclusively: the tier covers accrual below its threshold, and once the accrued company dollar reaches the threshold the tier is exhausted. Thresholds must be strictly ascending, the list must be non-empty, and the final element must carry a `broker_split_pct` of exactly 0 — the capped tier in which the agent keeps the entire post-royalty commission. A plan whose tiers are empty, not strictly ascending, or whose final tier is not the zero-split cap is rejected with `ERR_PLAN_TIERS_INVALID` (HTTP 422); the same rejection covers negative fee amounts on `eo_fee_cents` or `transaction_fee_cents`, while percentage fields outside the inclusive 0-to-1 interval (`royalty_pct`, `mentor_split_pct`, or any tier's `broker_split_pct`) are rejected with `ERR_PCT_OUT_OF_RANGE`.

A plan is born in `DRAFT` status and is editable only while `DRAFT`. Edits are a full replace of the plan's editable terms and must carry `expected_plan_version` per §2.7; a successful edit increments the plan's `version` by 1, and an attempt to edit a plan that has left `DRAFT` is rejected with `ERR_PLAN_INVALID_STATE` (HTTP 409). Activation moves a plan from `DRAFT` to `ACTIVE` — only `ACTIVE` plans accept enrollments — and retirement moves a plan from either `DRAFT` or `ACTIVE` to `RETIRED`, the terminal state. Retiring a plan that any enrollment still references in `ACTIVE` or `SCHEDULED` status is blocked with `ERR_PLAN_IN_USE` (HTTP 409); retiring an already-`RETIRED` plan or activating a non-`DRAFT` one is `ERR_PLAN_INVALID_STATE`. The plan listing supports a `status` filter.

### 3.3. Plan Enrollments and Effective-Dated Plan Changes

Enrolling an agent into a plan is a `BrokerAdmin` action whose payload carries the target `plan_id`, the `effective_from` date, and `expected_agent_version` under the optimistic-concurrency rule of §2.7. The agent must be `ACTIVE` — enrolling an agent in any other status is rejected with `ERR_AGENT_INVALID_STATE` — and the plan must be `ACTIVE`, else `ERR_PLAN_NOT_ACTIVE` (HTTP 409). Effective dating is strictly forward-chained: the new `effective_from` must be strictly after the `effective_from` of the agent's current `ACTIVE` or `SCHEDULED` enrollment, with no overlap and no back-dating over the current plan; a violation is `ERR_EFFECTIVE_DATE_REGRESSION` (HTTP 422). Only one pending plan change may exist at a time, so creating a second `SCHEDULED` enrollment for an agent who already has one is rejected with `ERR_ENROLLMENT_ALREADY_SCHEDULED` (HTTP 422).

Creation pins the plan's definition: the enrollment's `plan_version` records the plan's `version` as of enrollment, so later edits to the plan never rewrite the terms applied to deals covered by this enrollment. An enrollment created with an `effective_from` on or before the clock date activates inline: it is born `ACTIVE`, and the agent's previously `ACTIVE` enrollment, if any, is superseded — moved to `SUPERSEDED` with its `effective_to` set to the activating enrollment's `effective_from`. Both enrollments' `version` fields increment in that cascade, and the agent's `version` rises by exactly 1 for the whole enrollment-creation request. An enrollment created with a future `effective_from` instead sits in `SCHEDULED` with `effective_to` null — open-ended — until time catches up.

When the advancing clock reaches a `SCHEDULED` enrollment's `effective_from`, the sweep activates it with the identical supersede cascade on the agent's previously `ACTIVE` enrollment; on this sweep path the agent's `version` also increments. Termination cascades (§3.1) move an `ACTIVE` enrollment to `ENDED`, stamping `effective_to` with the termination date, and a `SCHEDULED` one to `CANCELLED` with a zero-length interval. `SUPERSEDED`, `ENDED`, and `CANCELLED` are the terminal enrollment states.

An enrollment **covers** a closing date when its `effective_from` is on or before the closing date and either its `effective_to` is null or the closing date falls strictly before `effective_to`. Settling a deal requires such a covering enrollment for the deal's agent; without one the settle is rejected with `ERR_NO_PLAN_ENROLLMENT` (HTTP 409). Enrollments can be listed filtered by `agent_id`, `plan_id`, or `status`; `Agent`-role callers see only their own enrollments.

### 3.4. Anniversary Windows: Accrual, Caps, and Book Closure

Every agent's production is measured against **anniversary windows** — consecutive one-year periods anchored to `joined_at`. A window's `window_index` is the 0-based count of whole years between `joined_at` and a given date: the greatest whole number of years that has fully elapsed, so window 0 runs from `joined_at` to the first anniversary. The `window_start` is `joined_at` advanced by `window_index` years — an agent who joined on February 29 starts their window on March 1 in non-leap years — and the `window_end` is the start of the following window. Windows are half-open: a date belongs to the window whose start is on or before it and whose end is strictly after it, so a closing date exactly equal to a `window_end` belongs to the next window. By construction the windows tile the agent's timeline exactly — no gaps, no overlaps.

Each window carries two accumulators, both starting at 0: `company_dollar_accrued_cents`, fed by posted settlements with the company dollar each produced, and `royalty_accrued_cents`, fed likewise with royalty. These running totals are what the royalty cap and tier thresholds of §3.6 consume. Rows are materialized lazily: the first settlement posting into a window creates the row, with its `status` derived from the clock at creation, and the clock sweep materializes every window from each non-`ONBOARDING` agent's join date through the window containing the new clock date.

A window is `OPEN` until the books close: when the clock date reaches or passes `window_end`, the sweep moves the window to `CLOSED` and increments its `version`. Settling a deal whose closing date falls in a `CLOSED` window is rejected with `ERR_WINDOW_CLOSED` (HTTP 409) — the books for that anniversary year are final. The window listing is ordered by `window_index` ascending and supports `agent_id` and `status` filters; `Agent`-role callers see only their own windows.

### 3.5. The Deal Pipeline: From Draft to Closing

A deal enters the system as a `DRAFT`, created either by an `Agent` for themself or by a `TransactionCoordinator` for any agent. The create payload names the credited agent via `agent_id`, the property `address`, the `gross_commission_cents` payable to the brokerage, and the expected `closing_date`, plus four optional terms: `cobroke_payout_cents` (default 0), the amount owed off the top to an outside co-broke brokerage; `cobroke_payee_name` (default null), that outside brokerage's payee name; `referral_pct` (default 0), the fraction of the post-cobroke net paid out as a referral fee; and `referral_agent_id` (default null), the in-house agent who referred the deal. An `Agent`-role caller may only create deals for themself — an `agent_id` that does not equal the caller's `X-User-ID` is rejected with `ERR_FORBIDDEN_RESOURCE` — and the credited agent must be `ACTIVE` at creation, else `ERR_AGENT_INVALID_STATE`.

Creation validates the deal's economics. The `gross_commission_cents` must be greater than zero, else `ERR_NONPOSITIVE_GROSS` (HTTP 422). The `cobroke_payout_cents` must be at least zero and strictly less than the gross, else `ERR_COBROKE_EXCEEDS_GROSS` (HTTP 422); and whenever a co-broke payout is present, `cobroke_payee_name` is required, else `ERR_COBROKE_PAYEE_MISSING` (HTTP 422). The `referral_pct` must lie between 0 and 1 inclusive, else `ERR_PCT_OUT_OF_RANGE`. A `referral_agent_id` must reference an existing Agent (`ERR_NOT_FOUND`) that differs from the deal's own `agent_id` (`ERR_SELF_REFERENCE`, HTTP 422), and the referral pair must be complete in both directions — a `referral_agent_id` with a zero or missing `referral_pct`, or a positive `referral_pct` with no `referral_agent_id`, is rejected with `ERR_REFERRAL_INCOMPLETE` (HTTP 422). Finally, the `closing_date` must not precede the agent's `joined_at`, a rule enforced at create, at update, and again at close using the effective values then in force; a violation is `ERR_DEAL_BEFORE_JOIN` (HTTP 422). A created deal starts with `trust_received_cents` at 0, and the credited agent is fixed for the life of the deal.

While the deal is `DRAFT`, the owning agent or a coordinator may edit it with a full replace of the editable terms — `address`, `gross_commission_cents`, `closing_date`, and the co-broke and referral fields — under exactly the same validations as creation. Submitting moves the deal from `DRAFT` to `PENDING_CLOSING`; withdrawing cycles it back from `PENDING_CLOSING` to `DRAFT` for further editing; both actions are open to the owning agent or a coordinator, with the same `ERR_FORBIDDEN_RESOURCE` ownership check for `Agent`-role callers. A deal that dies before closing is marked by a coordinator as `FELL_THROUGH`, and no money ever moves for it. Operating on a deal from a state that does not permit the action is rejected with `ERR_DEAL_INVALID_STATE` (HTTP 409), and each successful transition or edit increments the deal's `version` by 1.

Closing is the coordinator's act of record. The close action accepts two optional overrides — `actual_gross_commission_cents` and `actual_closing_date` — and the **effective** figures (each override when supplied, otherwise the deal's recorded value) drive validation: the effective gross must be greater than zero (`ERR_NONPOSITIVE_GROSS`), the effective closing date must not precede the agent's `joined_at` (`ERR_DEAL_BEFORE_JOIN`), and it must not lie after the clock date — future closings are rejected with `ERR_FUTURE_CLOSING` (HTTP 422). On a successful close from `PENDING_CLOSING`, the supplied actuals replace the deal's recorded `gross_commission_cents` and `closing_date`, `trust_received_cents` is set to the full gross commission, a trust `RECEIPT` transaction for that gross is created for the deal, and the deal lands in `CLOSED`. Voiding is the corrector for a closing recorded in error: it moves a deal from `CLOSED` to `VOIDED` — a `SETTLED` deal must be unsettled first — writing a trust `RECEIPT_REVERSAL` for the negated `trust_received_cents` and zeroing `trust_received_cents`. `FELL_THROUGH`, `VOIDED`, and ultimately `DISBURSED` (§3.7) are the deal's terminal states. The deal listing supports the filters `agent_id`, `referral_agent_id`, and `status`; `Agent`-role callers see only their own deals.

### 3.6. The Settlement Waterfall

Before any money moves, anyone may preview the schedule: a provisional payout estimate is available for a deal in `DRAFT`, `PENDING_CLOSING`, `CLOSED`, or `SETTLED` — asking for it on a `FELL_THROUGH` or `VOIDED` deal is rejected with `ERR_DEAL_INVALID_STATE`. The estimate runs the identical waterfall against the current accumulator and debit-balance state but produces no side effects whatsoever: no settlement, no legs, no ledger entries, no accumulator mutation. Its response carries a `variant` field set to `PROVISIONAL` alongside the full breakdown, from `gross_commission_cents` down to `agent_net_cents`. Because intervening settlements move the accumulators and the debit balance, the provisional estimate and the later final settlement legitimately differ for identical deal data.

Posting the real settlement — the `FINAL` variant of the same schedule — is the coordinator's settle action, which moves the deal from `CLOSED` to `SETTLED` and answers `201 Created` with the posted settlement. Four preconditions guard it: the deal must be `CLOSED` (settling a deal in any other state is `ERR_DEAL_INVALID_STATE`, and a `SETTLED` deal specifically is rejected with `ERR_DEAL_HAS_SETTLEMENT`, HTTP 409, since at most one non-`REVERSED` settlement may exist per deal); the anniversary window containing the `closing_date` must not be `CLOSED` (`ERR_WINDOW_CLOSED`); an enrollment of the deal's agent must cover the `closing_date` (`ERR_NO_PLAN_ENROLLMENT`); and no prior non-`REVERSED` settlement may exist for the deal.

The waterfall then evaluates in a pinned order. First, the closing date is assigned to its anniversary window by the rule of §3.4. Second, the covering enrollment is located, and third, the plan terms pinned on that enrollment's `plan_version` — recorded on the settlement as `plan_version_used` — become the governing schedule. Fourth, the window's accumulators are read **before** this deal posts: every previously posted, non-reversed settlement contributes to them regardless of its own closing date, so settlement-time order governs cap allocation — whichever deal settles first consumes cap room first. Fifth, the money flows through nine steps; only afterward, sixth, are the accumulators increased by this deal's company dollar and royalty.

- **Step 1 — co-broke off the top.** `cobroke_payout_cents` comes out first, leaving `net_office_commission_cents`, the gross minus the co-broke payout.
- **Step 2 — referral fee.** `referral_fee_cents` is `referral_pct` multiplied by `net_office_commission_cents`, rounded half up to whole cents here, before any later step consumes it. `adjusted_commission_cents` is the net office commission minus the referral fee.
- **Step 3 — franchise royalty with its annual cap.** A tentative royalty is `royalty_pct` times `adjusted_commission_cents`, rounded half up to whole cents. The cap room is the greater of zero and the plan's `royalty_cap_cents` minus the window's pre-deal `royalty_accrued_cents`. `royalty_cents` is the lesser of the tentative royalty and the cap room; `royalty_capped` is true exactly when the cap clipped the tentative amount. `after_royalty_cents` is the adjusted commission minus the royalty.
- **Step 4 — the tiered company split.** The applicable tier is the first tier, in ascending threshold order, whose `threshold_company_dollar_cents` strictly exceeds the window's pre-deal `company_dollar_accrued_cents`; when the accrued amount equals a threshold exactly, that tier is exhausted and the next tier applies. The settlement records the chosen tier as `tier_index_applied`. A tentative company dollar is `after_royalty_cents` multiplied by that tier's `broker_split_pct`, rounded half up to whole cents. The tier's cap room is the greater of zero and the tier's threshold minus the pre-deal accrued company dollar. `company_dollar_cents` is the lesser of the tentative company dollar and the cap room, and `cap_clipped` is true exactly when the cap clipped — marking the capping transaction, on which the agent keeps the entire surplus above the clipped company dollar and is not re-split at the next tier within the same deal. `agent_gross_cents` is `after_royalty_cents` minus `company_dollar_cents`.
- **Step 5 — mentor split.** The mentor split applies only when the agent has a `mentor_agent_id` and the agent's `settled_deal_count`, read before this deal posts, is strictly below the plan's `mentor_deal_count`. When it applies, `mentor_split_cents` is the plan's `mentor_split_pct` multiplied by `agent_gross_cents`, rounded half up to whole cents, and `mentor_applied` is true; otherwise `mentor_split_cents` is 0 and `mentor_applied` is false. The settlement snapshots the mentor into its own `mentor_agent_id` field for information, null when no mentor applied.
- **Step 6 — team override.** The team override applies only when the agent has a `team_lead_agent_id` and a `team_override_pct` greater than zero; when it applies, `team_override_cents` is `team_override_pct` multiplied by `agent_gross_cents`, rounded half up to whole cents, and otherwise it is 0. Both overrides are computed on the same base — `agent_gross_cents` — mentor first, and neither reduces the base of the other. The settlement likewise snapshots the team lead into `team_lead_agent_id`, null when no override applied.
- **Steps 7 and 8 — the flat fees, clipped by what remains.** Starting from the remainder of `agent_gross_cents` after the mentor split and team override, `eo_fee_cents` is deducted first as the lesser of the plan's `eo_fee_cents` and that remainder, then `transaction_fee_cents` as the lesser of the plan's `transaction_fee_cents` and what is still left. Whatever of the two flat fees could not be deducted accumulates into `fee_shortfall_cents` — the undeducted E&O plus transaction-fee shortfall — which is accrued to the agent's debit balance.
- **Step 9 — debit recovery.** `debit_recovery_cents` is the lesser of the agent share remaining after the fees and the agent's `debit_balance_cents` read before this deal posts; it is swept to the company. `agent_net_cents` — the cash payable to the agent — is `agent_gross_cents` minus the mentor split, the team override, the E&O fee, the transaction fee, and the debit recovery.

The posted settlement is a `POSTED` record carrying the full breakdown above together with its bookkeeping fields: `deal_id`, the denormalized `agent_id`, the `enrollment_id` whose coverage window contained the closing date, the informational `window_start` of the window posted to, `posted_by_user_id` recording the posting operator, and `posted_at` stamped from the logical clock; `reversed_at` stays null while the settlement stands. Settling then cascades, atomically: the window's `company_dollar_accrued_cents` rises by `company_dollar_cents` and its `royalty_accrued_cents` by `royalty_cents`, bumping the window's `version`; the agent's `settled_deal_count` rises by 1 and the agent's `version` increments; the deal's `version` increments; and the debit ledger responds to the fee outcomes in a pinned order — when `fee_shortfall_cents` is positive, a `FEE_SHORTFALL_ACCRUAL` ledger entry posts **first**, adding the shortfall to `debit_balance_cents`, and when `debit_recovery_cents` is positive, a `DEBIT_RECOVERY` entry posts **after** it, subtracting the recovery from `debit_balance_cents`. Recovery therefore sweeps only the pre-existing balance, never this deal's own fresh shortfall.

The same request also creates the settlement's disbursement legs, in a fixed creation order, each created only when its amount is greater than zero — zero-amount legs are never created:

1. a `CO_BROKE` leg for `cobroke_payout_cents`, paying the deal's `cobroke_payee_name`;
2. a `REFERRAL` leg for `referral_fee_cents`, paying the deal's `referral_agent_id`;
3. a `ROYALTY` leg for `royalty_cents`, paying the payee named `FRANCHISE`;
4. a `COMPANY` leg for the sum of `company_dollar_cents`, `eo_fee_cents`, `transaction_fee_cents`, and `debit_recovery_cents`, paying the payee named `COMPANY`;
5. a `MENTOR` leg for `mentor_split_cents`, paying the settlement's mentor;
6. a `TEAM_LEAD` leg for `team_override_cents`, paying the settlement's team lead;
7. an `AGENT` leg for `agent_net_cents`, paying the deal's credited agent.

The conservation invariant of §2.11 binds the whole schedule: the created legs always sum exactly to `gross_commission_cents`. Settlements can be listed filtered by `deal_id`, `agent_id`, `enrollment_id`, or `status`; `Agent`-role callers see only their own.

### 3.7. Disbursement: Legs, Authorization, and Release

Each disbursement leg is a single instructed payment out of the trust account. A leg records its `settlement_id`; a `payee_type` drawn from `AGENT`, `MENTOR`, `TEAM_LEAD`, `REFERRAL`, `CO_BROKE`, `ROYALTY`, or `COMPANY`; a `payee_agent_id` naming the payee for the four agent-backed types and null for `CO_BROKE`, `ROYALTY`, and `COMPANY`; a `payee_name` carrying the free-text co-broke payee, `FRANCHISE`, or `COMPANY` for the three non-agent types; and an `amount_cents` strictly greater than zero. Every leg is born `SCHEDULED`.

Authorization is the first signature: an `OfficeManager` or `BrokerAdmin` moves a leg from `SCHEDULED` to `AUTHORIZED`, which stamps `authorized_by_user_id` and `authorized_at` from the logical clock. Three guards apply — the leg must be `SCHEDULED`, else `ERR_LEG_INVALID_STATE` (HTTP 409); the caller must differ from the settlement's `posted_by_user_id` under §2.8, else `ERR_SEGREGATION_OF_DUTIES`; and the leg's settlement must still be `POSTED` with its deal still `SETTLED`, else `ERR_DEAL_INVALID_STATE`. Release is the second signature: an `OfficeManager` or `BrokerAdmin` moves an `AUTHORIZED` leg to `RELEASED` under the same state guards plus the mirror segregation rule — the caller must differ from the leg's `authorized_by_user_id`. Release stamps `released_by_user_id` and `released_at`, the latter being the cash-basis tax timestamp for 1099 purposes (§3.9); it writes a trust `RELEASE` transaction for the negated leg amount against the leg's deal; and it fires the bubble-up — when every leg of the settlement stands `RELEASED`, the deal transitions from `SETTLED` to `DISBURSED`. If any leg of the settlement was ever `VOIDED`, the deal can never reach `DISBURSED`; the correction path is to unsettle, fix the underlying terms, and settle again. Both authorization and release increment the leg's `version` by 1.

Voiding is the correction path before release: an `OfficeManager` or `BrokerAdmin` may move a leg from `SCHEDULED` or `AUTHORIZED` to `VOIDED`, and the unsettle cascade (§3.8) voids every still-`SCHEDULED` leg of the reversed settlement. Voiding from any other state is `ERR_LEG_INVALID_STATE`, and `RELEASED` is terminal — released money is gone, and corrections for it post as manual debit adjustments against the agent (§3.8). Legs can be listed filtered by `settlement_id`, `payee_agent_id`, `payee_type`, or `status`; `Agent`-role callers see only legs payable to themselves, and their read access to a single leg extends to legs where they are the payee or the deal's credited agent.

### 3.8. Corrections: Unsettle, the Agent Debit Ledger, and Trust Transactions

Unsettling is the full-reversal act, available to a `TransactionCoordinator` on a `SETTLED` deal whose settlement has nothing in flight: every leg of the settlement must be in `SCHEDULED` or `VOIDED`, and a leg standing `AUTHORIZED` or `RELEASED` blocks the reversal with `ERR_LEGS_OUTSTANDING` (HTTP 409); a deal in any state other than `SETTLED` is `ERR_DEAL_INVALID_STATE`. The unsettle cascade then runs atomically: the settlement moves from `POSTED` to `REVERSED` with `reversed_at` stamped from the clock and its `version` incremented; every leg of that settlement still `SCHEDULED` is moved to `VOIDED`; the anniversary window's accumulators are restored exactly — `company_dollar_accrued_cents` falls by the settlement's `company_dollar_cents` and `royalty_accrued_cents` by its `royalty_cents`, so cap room returns precisely; the agent's `settled_deal_count` falls by 1 and the agent's `version` increments; the deal returns to `CLOSED` with its `version` incremented; and the debit ledger is compensated — when the settlement had a positive `debit_recovery_cents`, a `DEBIT_RECOVERY_REVERSAL` entry adds that amount back to `debit_balance_cents`, and when it had a positive `fee_shortfall_cents`, a `FEE_SHORTFALL_REVERSAL` entry subtracts that amount from `debit_balance_cents`.

The debit ledger is the agent-facing record of what each agent owes the brokerage. Every entry carries the `agent_id` it moves; an `entry_type` drawn from `FEE_SHORTFALL_ACCRUAL`, `FEE_SHORTFALL_REVERSAL`, `DEBIT_RECOVERY`, `DEBIT_RECOVERY_REVERSAL`, `MANUAL_DEBIT`, and `DEBIT_WRITE_OFF`; a signed `amount_cents`, where positive increases the agent's debit balance and negative decreases it; and `resulting_balance_cents`, the running balance immediately after the entry. Settlement-driven entries also record the originating `deal_id` and the informational `settlement_id`, both null on manual adjustments, and manual entries carry a human `reason`. A `BrokerAdmin` posts a manual adjustment by supplying `amount_cents` and `reason`: a positive amount books a `MANUAL_DEBIT` — for example when the brokerage advances a cost on the agent's behalf — while a negative amount books a `DEBIT_WRITE_OFF` whose magnitude may not exceed the agent's current debit balance, else `ERR_WRITE_OFF_EXCEEDS_DEBIT` (HTTP 422). A zero `amount_cents` or a missing `reason` is rejected with `ERR_DEBIT_ADJUSTMENT_INVALID` (HTTP 422). Each adjustment moves `debit_balance_cents` by the signed amount and increments the agent's `version` by 1. The ledger listing is chronological in `created_at` ascending order and filters by `agent_id`, `deal_id`, or `entry_type`; `Agent`-role callers see only their own entries.

Trust transactions are the trust account's own journal. Each records a `deal_id`; a `kind` of `RECEIPT` (written at closing for the full gross), `RECEIPT_REVERSAL` (written at void for the negated gross), or `RELEASE` (written at leg release for the negated leg amount); the signed `amount_cents`; a `disbursement_leg_id` present only on `RELEASE` entries as an informational join; and `trust_balance_after_cents`, the global trust balance immediately after the transaction — the sum of all amounts to date. The trust transaction listing is chronological and filters by `deal_id` or `kind`. A separate read, restricted to `BrokerAdmin`, `OfficeManager`, and `Auditor`, reports the global trust position as `received_cents`, `released_cents`, `held_cents`, and a `transaction_count`, summed over every trust transaction in the system.

### 3.9. Year-End 1099 Reporting

Each agent is an independent contractor, so once a year the brokerage owes them a 1099 snapshot. A `BrokerAdmin` generates a form for an agent by supplying the `tax_year`, which must fall no earlier than the calendar year of the agent's `joined_at` and no later than the year of the clock date, else `ERR_TAX_YEAR_INVALID` (HTTP 422). Generation computes the figures as of that instant. If a `DRAFT` form already exists for the same agent and year, it is superseded — moved to `VOIDED` — and replaced by the new draft; if a `FINALIZED`, non-voided form exists for the same pair, generation is blocked outright with `ERR_TAX_FORM_FINALIZED_EXISTS` (HTTP 409).

Two totals are computed. The filed figure is cash-basis: `gross_paid_cents` sums the `amount_cents` of every disbursement leg payable to the agent — `AGENT`, `MENTOR`, `TEAM_LEAD`, and `REFERRAL` legs all count as contractor compensation — that stands `RELEASED` with a `released_at` on or after January 1 of the tax year and strictly before January 1 of the following year. The informational figure is accrual-basis: `accrual_gross_cents` sums the `agent_gross_cents` of the agent's own settlements that stand `POSTED` with a `posted_at` inside the calendar year, plus the amounts of `MENTOR`, `TEAM_LEAD`, and `REFERRAL` legs payable to the agent that were created inside the calendar year in any non-`VOIDED` status. Across a year boundary the two legitimately diverge: a December settlement whose legs release in January counts in the earlier year on the accrual basis and in the later year on the cash basis. `filing_required` is true exactly when `gross_paid_cents` reaches the reporting threshold of sixty thousand cents — the 600-dollar bar — inclusive.

A generated form starts in `DRAFT`. Finalizing moves it from `DRAFT` to `FINALIZED`, locking the snapshot for filing; voiding moves it from either `DRAFT` or `FINALIZED` to the terminal `VOIDED` state — the correction path after which a replacement draft may be generated. Finalizing or voiding from a state that does not permit it is rejected with `ERR_TAX_FORM_INVALID_STATE` (HTTP 409), and each transition increments the form's `version` by 1. The form listing filters by `agent_id`, `tax_year`, or `status`; `Agent`-role callers see only their own forms.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource — an agent, a commission plan, an enrollment, a deal, a settlement via the settle action, a ledger entry via a manual debit adjustment, or a 1099 form — return `201 Created`. All other successful operations, including reads, state transitions, edits, and clock advancement, return `200 OK`. Request payloads, validation rules, and side effects for each operation are specified in §2 and §3; the table below is an index, not a complete contract.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/brokerage/_clock/set_current_utc` | Advance the logical clock; run the enrollment-activation and window sweeps | BrokerAdmin |
| POST | `/brokerage/agents` | Create an agent in `ONBOARDING` | BrokerAdmin |
| GET | `/brokerage/agents/{agentId}` | Get one agent | BrokerAdmin, OfficeManager, TransactionCoordinator, Auditor, Agent |
| GET | `/brokerage/agents` | List agents with filters | BrokerAdmin, OfficeManager, TransactionCoordinator, Auditor, Agent |
| PATCH | `/brokerage/agents/{agentId}` | Update mutable agent fields (optimistic concurrency on the agent version) | BrokerAdmin |
| POST | `/brokerage/agents/{agentId}/activate` | `ONBOARDING` → `ACTIVE` | BrokerAdmin |
| POST | `/brokerage/agents/{agentId}/suspend` | `ACTIVE` → `SUSPENDED` | BrokerAdmin |
| POST | `/brokerage/agents/{agentId}/reinstate` | `SUSPENDED` → `ACTIVE` | BrokerAdmin |
| POST | `/brokerage/agents/{agentId}/terminate` | Terminate an agent; cascades enrollments to `ENDED`/`CANCELLED` | BrokerAdmin |
| POST | `/brokerage/plans` | Create a commission plan in `DRAFT` | BrokerAdmin |
| GET | `/brokerage/plans/{planId}` | Get one plan | BrokerAdmin, OfficeManager, TransactionCoordinator, Auditor, Agent |
| GET | `/brokerage/plans` | List plans | BrokerAdmin, OfficeManager, TransactionCoordinator, Auditor, Agent |
| PUT | `/brokerage/plans/{planId}` | Full replace of a `DRAFT` plan's terms (optimistic concurrency on the plan version) | BrokerAdmin |
| POST | `/brokerage/plans/{planId}/activate` | `DRAFT` → `ACTIVE` | BrokerAdmin |
| POST | `/brokerage/plans/{planId}/retire` | `DRAFT`/`ACTIVE` → `RETIRED`, blocked while in use | BrokerAdmin |
| POST | `/brokerage/agents/{agentId}/enrollments` | Enroll an agent into a plan with effective dating (optimistic concurrency on the agent version) | BrokerAdmin |
| GET | `/brokerage/enrollments/{enrollmentId}` | Get one enrollment | BrokerAdmin, OfficeManager, TransactionCoordinator, Auditor, Agent |
| GET | `/brokerage/enrollments` | List enrollments filtered by agent, plan, or status | BrokerAdmin, OfficeManager, TransactionCoordinator, Auditor, Agent |
| GET | `/brokerage/anniversary-periods/{periodId}` | Get one anniversary period | BrokerAdmin, OfficeManager, TransactionCoordinator, Auditor, Agent |
| GET | `/brokerage/anniversary-periods` | List anniversary windows ordered by `window_index` ascending | BrokerAdmin, OfficeManager, TransactionCoordinator, Auditor, Agent |
| POST | `/brokerage/deals` | Create a deal in `DRAFT` | Agent, TransactionCoordinator |
| GET | `/brokerage/deals/{dealId}` | Get one deal | BrokerAdmin, OfficeManager, TransactionCoordinator, Auditor, Agent |
| GET | `/brokerage/deals` | List deals | BrokerAdmin, OfficeManager, TransactionCoordinator, Auditor, Agent |
| PUT | `/brokerage/deals/{dealId}` | Full replace of a `DRAFT` deal's editable terms | Agent, TransactionCoordinator |
| POST | `/brokerage/deals/{dealId}/submit` | `DRAFT` → `PENDING_CLOSING` | Agent, TransactionCoordinator |
| POST | `/brokerage/deals/{dealId}/withdraw` | `PENDING_CLOSING` → `DRAFT` | Agent, TransactionCoordinator |
| POST | `/brokerage/deals/{dealId}/fall-through` | `PENDING_CLOSING` → `FELL_THROUGH`; no money moves | TransactionCoordinator |
| POST | `/brokerage/deals/{dealId}/close` | `PENDING_CLOSING` → `CLOSED`; records actuals and the trust receipt | TransactionCoordinator |
| POST | `/brokerage/deals/{dealId}/void` | `CLOSED` → `VOIDED`; reverses the trust receipt | TransactionCoordinator |
| GET | `/brokerage/deals/{dealId}/payout-estimate` | Provisional payout schedule against current state; no side effects | BrokerAdmin, OfficeManager, TransactionCoordinator, Auditor, Agent |
| POST | `/brokerage/deals/{dealId}/settle` | `CLOSED` → `SETTLED`; posts the settlement, legs, ledger entries, and accumulator updates atomically | TransactionCoordinator |
| POST | `/brokerage/deals/{dealId}/unsettle` | `SETTLED` → `CLOSED`; full reversal cascade | TransactionCoordinator |
| GET | `/brokerage/settlements/{settlementId}` | Get one settlement with the full waterfall breakdown | BrokerAdmin, OfficeManager, TransactionCoordinator, Auditor, Agent |
| GET | `/brokerage/settlements` | List settlements | BrokerAdmin, OfficeManager, TransactionCoordinator, Auditor, Agent |
| GET | `/brokerage/disbursement-legs/{legId}` | Get one disbursement leg | BrokerAdmin, OfficeManager, TransactionCoordinator, Auditor, Agent |
| GET | `/brokerage/disbursement-legs` | List disbursement legs | BrokerAdmin, OfficeManager, TransactionCoordinator, Auditor, Agent |
| POST | `/brokerage/disbursement-legs/{legId}/authorize` | `SCHEDULED` → `AUTHORIZED`; authorizer must differ from the settlement poster | OfficeManager, BrokerAdmin |
| POST | `/brokerage/disbursement-legs/{legId}/release` | `AUTHORIZED` → `RELEASED`; releaser must differ from the authorizer; may bubble the deal to `DISBURSED` | OfficeManager, BrokerAdmin |
| POST | `/brokerage/disbursement-legs/{legId}/void` | `SCHEDULED`/`AUTHORIZED` → `VOIDED` | OfficeManager, BrokerAdmin |
| GET | `/brokerage/ledger-entries/{entryId}` | Get one ledger entry | BrokerAdmin, OfficeManager, TransactionCoordinator, Auditor, Agent |
| GET | `/brokerage/ledger-entries` | List debit-ledger entries chronologically | BrokerAdmin, OfficeManager, TransactionCoordinator, Auditor, Agent |
| POST | `/brokerage/agents/{agentId}/debit-adjustments` | Post a manual debit or write-off against an agent | BrokerAdmin |
| POST | `/brokerage/agents/{agentId}/tax-forms` | Generate a `DRAFT` 1099 snapshot for a tax year | BrokerAdmin |
| GET | `/brokerage/tax-forms/{taxFormId}` | Get one tax form | BrokerAdmin, OfficeManager, TransactionCoordinator, Auditor, Agent |
| GET | `/brokerage/tax-forms` | List tax forms | BrokerAdmin, OfficeManager, TransactionCoordinator, Auditor, Agent |
| POST | `/brokerage/tax-forms/{taxFormId}/finalize` | `DRAFT` → `FINALIZED`; locks the snapshot for filing | BrokerAdmin |
| POST | `/brokerage/tax-forms/{taxFormId}/void` | `DRAFT`/`FINALIZED` → `VOIDED` | BrokerAdmin |
| GET | `/brokerage/trust-transactions/{transactionId}` | Get one trust transaction | BrokerAdmin, OfficeManager, Auditor |
| GET | `/brokerage/trust-ledger` | Global trust position: received, released, and held balances | BrokerAdmin, OfficeManager, Auditor |
| GET | `/brokerage/trust-transactions` | List trust transactions chronologically | BrokerAdmin, OfficeManager, TransactionCoordinator, Auditor, Agent |

## 5. Error Code Catalogue

Trigger conditions for each error live with the workflows that raise them in §2 and §3; this table is an index of identifiers to HTTP status codes.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_USER_CONTEXT` | 400 Bad Request |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_FORBIDDEN_FOR_ROLE` | 403 Forbidden |
| `ERR_UNKNOWN_USER_IDENTITY` | 403 Forbidden |
| `ERR_FORBIDDEN_RESOURCE` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_STALE_AGENT_VERSION` | 412 Precondition Failed |
| `ERR_STALE_PLAN_VERSION` | 412 Precondition Failed |
| `ERR_AGENT_INVALID_STATE` | 409 Conflict |
| `ERR_PLAN_INVALID_STATE` | 409 Conflict |
| `ERR_PLAN_NOT_ACTIVE` | 409 Conflict |
| `ERR_PLAN_IN_USE` | 409 Conflict |
| `ERR_ENROLLMENT_ALREADY_SCHEDULED` | 422 Unprocessable Entity |
| `ERR_EFFECTIVE_DATE_REGRESSION` | 422 Unprocessable Entity |
| `ERR_NO_PLAN_ENROLLMENT` | 409 Conflict |
| `ERR_WINDOW_CLOSED` | 409 Conflict |
| `ERR_DEAL_INVALID_STATE` | 409 Conflict |
| `ERR_DEAL_HAS_SETTLEMENT` | 409 Conflict |
| `ERR_DEAL_BEFORE_JOIN` | 422 Unprocessable Entity |
| `ERR_FUTURE_CLOSING` | 422 Unprocessable Entity |
| `ERR_CLOCK_REGRESSION` | 422 Unprocessable Entity |
| `ERR_AGENT_HAS_OPEN_DEALS` | 409 Conflict |
| `ERR_LEG_INVALID_STATE` | 409 Conflict |
| `ERR_LEGS_OUTSTANDING` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_NONPOSITIVE_GROSS` | 422 Unprocessable Entity |
| `ERR_COBROKE_EXCEEDS_GROSS` | 422 Unprocessable Entity |
| `ERR_PCT_OUT_OF_RANGE` | 422 Unprocessable Entity |
| `ERR_PLAN_TIERS_INVALID` | 422 Unprocessable Entity |
| `ERR_REFERRAL_INCOMPLETE` | 422 Unprocessable Entity |
| `ERR_COBROKE_PAYEE_MISSING` | 422 Unprocessable Entity |
| `ERR_SELF_REFERENCE` | 422 Unprocessable Entity |
| `ERR_LICENSE_NUMBER_TAKEN` | 409 Conflict |
| `ERR_TAX_YEAR_INVALID` | 422 Unprocessable Entity |
| `ERR_TAX_FORM_FINALIZED_EXISTS` | 409 Conflict |
| `ERR_TAX_FORM_INVALID_STATE` | 409 Conflict |
| `ERR_DEBIT_ADJUSTMENT_INVALID` | 422 Unprocessable Entity |
| `ERR_WRITE_OFF_EXCEEDS_DEBIT` | 422 Unprocessable Entity |
