# Mechanics Lien Service API — Product Requirements Document

## 1. Introduction

Every year, construction suppliers and subcontractors forfeit payment rights they were legally owed — not because the debt was disputed, but because a statutory deadline slipped. Each US state imposes its own mechanics-lien calendar: a preliminary notice due within a fixed number of days of first furnishing, a lien filing window measured from last furnishing, a foreclosure suit deadline measured from recording, and entirely different remedies — stop notices and payment-bond claims — on public projects where liens against the property are not permitted at all. The rules shift again with the project type, the delivery method used, and even with whether a refused certified letter still counts as proof of service.

This document specifies the Mechanics Lien Service API, a compliance-grade platform mounted under `/lien` that manages the full lien lifecycle on behalf of claimant companies: researching owners, general contractors, lenders, and sureties; recording furnishing spans; ordering, serving, and proving preliminary notices; reconciling claim amounts against waivers and payments; filing, releasing, bonding around, and foreclosing liens; and pursuing stop notices and bond claims on public work. Two design commitments run through everything that follows. First, every deadline is derived from a deterministic logical clock rather than wall-clock time, so the platform's notion of *today* is explicit and auditable. Second, every mutation and all of its cascading side effects are visible within that request's own response — there is no eventual consistency anywhere in the system.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, conventions, and guarantees that apply to every endpoint of the API.

### 2.1. User and Role-Based Access Control

All interactions with the API are authenticated through two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring their operational capacity. The system recognizes exactly four roles, spelled precisely as follows: `PlatformAdmin`, `OpsAgent`, `CustomerAdmin`, and `Counsel`.

- `PlatformAdmin` is service operator staff; it configures jurisdiction rules, company accounts, prepaid balance adjustments, and the logical clock.
- `OpsAgent` is a service operations agent; it verifies research and parties, serves notices, records delivery proof, files liens, applies waivers, verifies payments, records bonds, and processes stop notices and bond claims.
- `CustomerAdmin` administers a claimant company; it owns projects, orders notices, and manages lien claims, waivers, payments, bonding requests, foreclosure referrals, stop notices, and bond claims.
- `Counsel` is external foreclosure counsel; it responds to foreclosure referrals and marks foreclosure suits filed.

A request whose `X-User-Role` header is missing or does not name one of these four roles is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not authorized for the targeted operation is rejected with `ERR_FORBIDDEN` (HTTP 403).

Role identity determines what `X-User-ID` means. When `X-User-Role` is `CustomerAdmin`, `X-User-ID` is the `id` of the acting `Company`; ownership checks on any resource that references a `Company` compare the resource's foreign-key field to `X-User-ID`. Every project a `CustomerAdmin` creates is stamped with that company's id as its `company_id`, and a `CustomerAdmin` may only access resources whose owning project's `company_id` equals their own `X-User-ID`; attempts against another company's resources are rejected with `ERR_FORBIDDEN` (HTTP 403). When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity, and the same holds when `X-User-Role` is `OpsAgent` and when it is `Counsel`; for these three roles the server does not compare `X-User-ID` against any entity's `id`, and none of them is company-scoped.

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

Endpoints that return lists of resources are paginated through two query parameters. The `limit` parameter specifies the maximum number of items to return; when omitted it defaults to 10, and it is bounded below by 1 and above by 100. The `offset` parameter specifies how many items to skip and defaults to 0. A `limit` or `offset` that is not an integer, a `limit` outside the 1–100 bounds, or a negative `offset` is rejected with `ERR_VALIDATION` (HTTP 400).

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order, with ties broken by `id` in ascending order.

Paginated list responses carry the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Resource Identity, Timestamps, and Version Counters

Every resource in the system — companies, jurisdiction rules, projects, parties, furnishing spans, notice orders, lien claims, waivers, payments, bonding requests, foreclosure referrals, stop notices, and bond claims — carries the same four system-managed properties:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, assigned when the resource is created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed whenever any property of the resource changes.
- `version` (integer): a counter that starts at 1 when the resource is created and increments by one on every mutation of the resource, including mutations produced by cascades that originate on other resources.

No entity in this domain is exempt from this convention: every resource type carries the full set, so every resource presents a consistent audit trail and an optimistic-concurrency token.

### 2.5. The Logical Clock and Lazy Statutory Expiry

The platform never consults wall-clock time. At server start the logical clock reads exactly 2026-05-01T00:00:00Z, and it advances only when a `PlatformAdmin` invokes the clock-setting capability with a `to_iso8601` instant; the response echoes the new value as `current_utc`. All deadline arithmetic, all timeliness checks, and all rule-effectiveness comparisons are evaluated against this clock and against nothing else.

Statutory expiry is lazy. Notice orders, lien claims, stop notices, and bond claims each carry an `EXPIRED` state entered by an automatic transition — but that transition is applied only when the affected entity is next read or is next targeted by a mutation, at which point every due auto-transition is applied first and reflected in that same response. A client reading a stale draft notice therefore observes `EXPIRED`, never a silently out-of-date `DRAFT`. Combined with the platform's immediate consistency model, readers can always trust that a returned resource reflects every transition its deadlines demand.

### 2.6. Day Reckoning: Calendar and Business Day Bases

Dates are handled at day granularity as ISO calendar dates. A jurisdiction rule declares a `prelim_day_basis` of either `CALENDAR` or `BUSINESS`, which governs how its `prelim_days` count is added to a date. Under the `CALENDAR` basis every day on the calendar counts. Under the `BUSINESS` basis only days that are neither Saturday nor Sunday count, and the platform observes no holiday calendar. Every other day addition in the system — filing windows, foreclosure deadlines, stop-notice and bond-claim deadlines — is a simple calendar-day addition.

Every statutory deadline treats its final day as usable: an action performed on the deadline day itself is timely, and only a date strictly after the deadline fails. This inclusive-last-day convention applies uniformly to preliminary notice service, lien filing, stop notice service, bond claim submission, and foreclosure suit filing.

### 2.7. Jurisdiction Rule Versions and Pinned vs. Live Rules

For each pairing of a two-letter `state_code` and a `project_type` — one of `COMMERCIAL_PRIVATE`, `RESIDENTIAL_PRIVATE`, `STATE_PUBLIC`, or `FEDERAL_PUBLIC` — at most one jurisdiction rule may be `PUBLISHED` at a time. Rules are never edited in place. Instead, a `PlatformAdmin` supersedes the published rule, which creates a successor rule carrying the addressed rule's `state_code` and `project_type`, links the successor to its predecessor through `supersedes_rule_id`, and moves the predecessor to `SUPERSEDED`. Original rules created directly rather than by supersession carry a null `supersedes_rule_id`. The chain remains readable in both directions: the successors of any rule can be listed, and the lien claims that pinned a rule at lock can be listed as well.

Which rule is *effective* for live projections is a function of the clock. Among the `PUBLISHED` rules matching a project's `state_code` and `project_type`, the effective rule is the one with the greatest `effective_from` that is not later than the current clock date; ties are broken in favor of the rule created earliest. When no published rule matches at all, every live projection is null.

Pinning completes the picture. Draft artifacts — an unserved notice's deadline, a project's deadline calendar, a stop notice's or bond claim's timeliness window — always recompute live against the currently effective rule. The moment a lien claim is locked, however, it pins the effective rule's identity as `locked_rule_id`, and everything the claim derives from that rule — the filing window end, the foreclosure deadline, the bonding percentage, the interest rate — is governed by the pinned version forever, immune to later supersessions.

### 2.8. Monetary Precision and Rounding

All money in the system is handled as integer cents; fractional cents never reach a stored or returned value. Claim amounts — provisional, final, and outstanding — are exact integer-cent computations with no rounding. Where a computation genuinely produces fractions, the result is rounded half-up to whole cents: this applies to each line of a notice fee quote, to the bond amount of a bonding request, and to pre-judgment interest on a filed claim. Multi-line computations round each line first and then sum the rounded lines, in that order.

### 2.9. Optimistic Concurrency Control

Three write operations are guarded by optimistic concurrency control, each keyed to a parent entity's `version`:

- `POST /lien/furnishing-spans` requires `expected_project_version`, carrying the client's last observed `version` of the parent project.
- `POST /lien/companies/{id}/balance-adjustments` requires `expected_company_version`, carrying the client's last observed `version` of the company.
- `POST /lien/jurisdiction-rules/{id}/supersede` requires `expected_jurisdiction_rule_version`, carrying the client's last observed `version` of the addressed rule.

On each of these endpoints the expected-version field is mandatory. If the supplied value no longer matches the parent entity's current `version` — because another write has advanced that entity since the client last read it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), protecting the client from overwriting state it has not observed. Endpoints not listed here accept no version field at all.

### 2.10. Validation Order and Nested Resource Retrieval

Before business validation begins, a request whose payload is malformed — a missing required field, an unknown field, or an invalid enumeration or format value — is rejected with `ERR_VALIDATION` (HTTP 400).

All remaining checks run as a fixed ladder. The first failing rung determines the response, and later rungs are never evaluated for that request:

1. **Authentication** — the `X-User-Role` header must be present and name a declared role, else `ERR_UNAUTHENTICATED` (HTTP 401).
2. **Endpoint authorization** — the acting role must be permitted on the endpoint, else `ERR_FORBIDDEN` (HTTP 403).
3. **Company scoping** — a `CustomerAdmin` must stay within their own company's resources, else `ERR_FORBIDDEN` (HTTP 403).
4. **Existence** — every identifier in the path is resolved left to right, and every foreign-key identifier in the body must exist, else `ERR_NOT_FOUND` (HTTP 404). On nested paths the leftmost missing identifier produces the 404 before any identifier to its right is examined.
5. **State preconditions** (HTTP 409) — the target resource must be in a state that permits the operation. The specific state errors take this slot: `ERR_RESEARCH_ALREADY_VERIFIED`, `ERR_CLAIM_NOT_LOCKED`, `ERR_CLAIM_NOT_FILED`, `ERR_NOTICE_NOT_SERVED`, `ERR_WAIVER_NOT_RECEIVED`, and `ERR_RULE_NOT_PUBLISHED`; when no specific state error applies, the generic `ERR_INVALID_STATE` is used.
6. **Optimistic concurrency** (HTTP 412) — a stale expected-version field on one of the three guarded writes yields `ERR_STALE_VERSION`.
7. **Compliance gates** — `ERR_PROJECT_NOT_VERIFIED` (409), `ERR_PARTIES_UNVERIFIED` (409), `ERR_LIEN_NOT_PERMITTED_PUBLIC` (422), `ERR_STOP_NOTICE_NOT_PERMITTED` (422), `ERR_BOND_CLAIM_NOT_PERMITTED` (422), and `ERR_DELIVERY_METHOD_NOT_ALLOWED` (422).
8. **Referential consistency** — `ERR_PARTY_PROJECT_MISMATCH` (422), `ERR_SURETY_NOT_VERIFIED` (409), and `ERR_PARTY_NOT_VERIFIED` (409).
9. **Temporal and deadline checks** — `ERR_SPAN_DATES_INVALID` (422), `ERR_NOTICE_DEADLINE_PASSED` (409), `ERR_FILING_WINDOW_CLOSED` (409), `ERR_STOP_NOTICE_DEADLINE_PASSED` (409), `ERR_BOND_CLAIM_DEADLINE_PASSED` (409), and `ERR_FORECLOSURE_DEADLINE_PASSED` (409).
10. **Uniqueness and aggregate constraints** (HTTP 409) — `ERR_RULE_ALREADY_PUBLISHED`, `ERR_OPEN_CLAIM_EXISTS`, `ERR_OPEN_BONDING_EXISTS`, `ERR_OPEN_REFERRAL_EXISTS`, `ERR_WAIVER_PERIOD_OVERLAP`, `ERR_STOP_NOTICE_OVERLAP`, and `ERR_NO_ACTIVE_SPAN`.
11. **Fiscal checks, always last** — `ERR_AMOUNT_MUST_BE_POSITIVE` (422), `ERR_INSUFFICIENT_BALANCE` (402), and `ERR_ZERO_CLAIM_AMOUNT` (422).

Because the rungs are ordered, the error a client observes is deterministic. A notice order that would fail both for a disallowed delivery method and for insufficient funds reports `ERR_DELIVERY_METHOD_NOT_ALLOWED`, never `ERR_INSUFFICIENT_BALANCE`; a rule supersession against a rule that is no longer `PUBLISHED` reports `ERR_RULE_NOT_PUBLISHED` even when its expected-version field is also stale, because state preconditions sit above the concurrency rung.

## 3. Business Logic & Workflows

### 3.1. Company Accounts and Jurisdiction Rule Administration

Everything begins with the claimant company. A `PlatformAdmin` creates a `Company` by supplying its legal `name` and billing `contact_email`; the account starts life with a `prepaid_balance_cents` of zero and an `open_notice_count` of zero. The prepaid balance is the platform's purse: every preliminary notice order debits it, and a `PlatformAdmin` tops it up or draws it down through balance adjustments carrying an `amount_cents` (positive to credit, negative to debit) and a free-text `reason`. Because a notice-fee debit and an operator-posted adjustment both move the same balance, adjustments are concurrency-guarded: the request must carry `expected_company_version` equal to the company's current `version`, or it is rejected with `ERR_STALE_VERSION` (HTTP 412). A successful adjustment moves `prepaid_balance_cents` by exactly `amount_cents` and increments the company's `version` by one, responding `201 Created` with the updated company.

Jurisdiction configuration is the other half of platform administration. Publishing the first rule for a `state_code` and `project_type` pair requires the full statutory profile: `prelim_notice_required`, `prelim_days`, `prelim_day_basis`, `refused_counts_as_served`, `allowed_delivery_methods` (a subset of `CERTIFIED_MAIL`, `PERSONAL_SERVICE`, and `EMAIL_STATUTORY`), `filing_window_days`, `foreclosure_deadline_days`, `stop_notice_days`, `bond_claim_days`, `counts_punch_list`, `retainage_claimable`, `cap_mode`, `interest_annual_rate`, `bond_pct`, and `effective_from`. If a `PUBLISHED` rule already exists for the pair, creation is rejected with `ERR_RULE_ALREADY_PUBLISHED` (HTTP 409) — the operator must supersede instead. A freshly published rule starts in `PUBLISHED` status with a null `supersedes_rule_id`.

Supersession rewrites the law of a jurisdiction without touching history. A `PlatformAdmin` supersedes an existing rule by providing the complete replacement profile together with `expected_jurisdiction_rule_version`. The addressed rule must currently be `PUBLISHED`, or the request fails with `ERR_RULE_NOT_PUBLISHED` (HTTP 409); a stale expected version fails with `ERR_STALE_VERSION` (HTTP 412). On success, a successor rule is created in `PUBLISHED` status carrying the addressed rule's `state_code` and `project_type` and recording the predecessor in `supersedes_rule_id`, while the addressed rule moves to `SUPERSEDED` and its `version` increments by one.

Supersession then cascades outward. Every project matching the rule's `state_code` and `project_type` has its projected deadlines — furnishing-date determination, preliminary-notice deadline, and the lien windows — recomputed live against the successor. Any of those projects' `DRAFT` notice orders whose recomputed `service_deadline` now falls before the current clock date auto-transition from `DRAFT` to `EXPIRED`, and each such expiry decrements the owning project's `open_notice_count` and the owning company's `open_notice_count` by one.

### 3.2. Project Intake, Party Research, and Verification

A `CustomerAdmin` opens a project by supplying its `name`, the property's `state_code` and `county` (the recording jurisdiction), the `project_type`, the `property_legal_description` captured during research, and the financial envelope of the job: `contract_value_cents`, `approved_extras_cents`, and `retainage_held_cents`. The new project's `company_id` is taken from the caller's `X-User-ID`, its `research_status` starts at `UNRESEARCHED`, its `lien_posture` starts at `CLEAR`, and both of its open counters start at zero.

Parties are the people a lien practice must name correctly. A `CustomerAdmin` records each party with its `project_id`, a `party_role` of `OWNER`, `GC`, `LENDER`, `HIRER`, or `SURETY`, plus the researched `legal_name` and service `address`; every party starts with `research_status` `PENDING`. An `OpsAgent` then adjudicates the research by submitting an `outcome`, moving the party to `VERIFIED` or `FAILED`; the decision is accepted regardless of the party's current `research_status` and overwrites it.

Research on the project itself advances in two steps, both performed by an `OpsAgent`. From `UNRESEARCHED` the project moves to `RESEARCHED` unconditionally; from `RESEARCHED` it moves to `VERIFIED` only when every required party is itself `VERIFIED` — the `OWNER` and the `GC` always, and the `LENDER` as well whenever the effective rule's `prelim_notice_required` is true — failing which the advance is rejected with `ERR_PARTIES_UNVERIFIED` (HTTP 409). Each successful advance increments the project's `version` by one. Advancing a project that is already `VERIFIED` always fails with `ERR_RESEARCH_ALREADY_VERIFIED` (HTTP 409).

A project's `lien_posture` is computed, never set directly, and is recomputed after every mutation that touches the project's lien claims, foreclosure referrals, notice orders, stop notices, or bond claims. The tiers are evaluated in strict priority order: the posture is `LITIGATION` when any lien claim on the project is `FORECLOSED` or any foreclosure referral is `SUIT_FILED`; failing that, `ENCUMBERED` when any lien claim is `FILED`, any stop notice is `SERVED`, or any bond claim is `SUBMITTED`; failing that, `NOTICED` when any notice order is `SERVED` or `PROOF_CONFIRMED`; and `CLEAR` otherwise.

### 3.3. Furnishing Spans and the Project Deadline Calendar

Furnishing spans are the raw material of every statutory deadline. A `CustomerAdmin` records a span with its `project_id`, a `span_kind` of `BASE_CONTRACT`, `CHANGE_ORDER`, `PUNCH_LIST`, or `WARRANTY`, and a `start_date` and `end_date`; an `end_date` earlier than the `start_date` is rejected with `ERR_SPAN_DATES_INVALID` (HTTP 422). Creating a span supersedes any prior `ACTIVE` span of the same kind on the same project: the prior span moves to `SUPERSEDED` with its `updated_at` refreshed, the project's furnishing dates are recomputed over the remaining `ACTIVE` spans, and the project's `version` increments by one. Because recording a span both supersedes its predecessor and mutates the project's dates, the create is concurrency-guarded — it must carry `expected_project_version` matching the project's current `version`, and a stale value is rejected with `ERR_STALE_VERSION` (HTTP 412).

From the `ACTIVE` spans the platform derives two dates. The project's `first_furnishing_date` is the earliest `start_date` among them, or null when no `ACTIVE` span exists. The `last_furnishing_date` depends on a variant selected by the effective rule's `counts_punch_list`. Under the strict variant — `counts_punch_list` false — only `BASE_CONTRACT` and `CHANGE_ORDER` spans are considered, and `PUNCH_LIST` and `WARRANTY` spans never extend last furnishing. Under the inclusive variant — `counts_punch_list` true — the latest `end_date` across all `ACTIVE` spans wins, so identical inputs can yield a later date than strict. An empty candidate set yields null in both variants, and both dates recompute whenever a span is created or superseded, whenever the effective rule changes through supersession, and whenever the project or its deadline calendar is read.

The deadline calendar is a computed read over a project's jurisdiction. It reports `applied_rule_id` — the effective rule chosen per §2.7 — together with three projected deadlines: `prelim_notice_deadline`, the `first_furnishing_date` plus the rule's `prelim_days` counted on its `prelim_day_basis`; `filing_window_end`, the `last_furnishing_date` plus the rule's `filing_window_days`; and `stop_notice_deadline`, the `last_furnishing_date` plus the rule's `stop_notice_days`. It also echoes the `last_furnishing_date` itself and a `last_furnishing_variant` identifying which determination variant produced it — the lowercase string `strict` or `inclusive`, or null when the project has no `ACTIVE` span. When no published rule matches the project's jurisdiction, `applied_rule_id` and every deadline field are null; when a rule matches but the project has no `ACTIVE` span, `prelim_notice_deadline` is null; and when there is no last furnishing date, `filing_window_end` and `stop_notice_deadline` are null. Locked or filed claims on the project ignore this projection entirely — they keep the rule pinned at lock.

Any operation whose deadline arithmetic requires furnishing dates fails fast when the project has no `ACTIVE` span: ordering a preliminary notice, creating or serving a stop notice, and submitting a bond claim are rejected with `ERR_NO_ACTIVE_SPAN` (HTTP 409); a missing effective rule, which likewise makes the deadline uncomputable, yields the same error on the serve and submit operations.

### 3.4. Preliminary Notice Orders: Fees, Service, and Delivery Proof

A `CustomerAdmin` orders a preliminary notice by naming the `project_id`, the `recipient_party_id`, and the `delivery_method`. The order runs the full validation ladder: the project must be `VERIFIED` — notice creation and notice service alike require it, failing with `ERR_PROJECT_NOT_VERIFIED` (HTTP 409) — the recipient must exist, belong to the same project (`ERR_PARTY_PROJECT_MISMATCH`, HTTP 422), and be `VERIFIED` (`ERR_PARTY_NOT_VERIFIED`, HTTP 409); the `delivery_method` must appear in the effective rule's `allowed_delivery_methods` (`ERR_DELIVERY_METHOD_NOT_ALLOWED`, HTTP 422); an `ACTIVE` furnishing span must exist to compute the deadline (`ERR_NO_ACTIVE_SPAN`); and the company's `prepaid_balance_cents` must cover the quoted fee (`ERR_INSUFFICIENT_BALANCE`, HTTP 402).

The quoted `fee_cents` is the sum of two lines, each rounded half-up to whole cents before the lines are added. The recipient line starts from a base of 1499 cents; when the recipient party's `party_role` is `LENDER`, a 15 percent surcharge is applied to that base and the result rounded half-up to whole cents, while any other recipient role yields simply 1499 cents. The delivery line starts from a base of 899 cents multiplied by the factor for the chosen `delivery_method` — exactly one times for `CERTIFIED_MAIL`, two and a half times for `PERSONAL_SERVICE`, and one half for `EMAIL_STATUTORY` — rounded half-up to whole cents. Rounding each line first and then summing is the pinned evaluation order; summing the unrounded lines and rounding once is forbidden, because it can produce a different cent value. The fee is debited from the company's `prepaid_balance_cents` at creation, incrementing the company's `version` by one, and both the project's and the company's `open_notice_count` increment by one.

A new notice is a `DRAFT` whose `service_deadline` is the project's `first_furnishing_date` plus the effective rule's `prelim_days`, counted on the rule's `prelim_day_basis`. While the notice remains `DRAFT` the deadline is recomputed live whenever the effective rule changes; once served, the deadline freezes.

An `OpsAgent` serves the notice by recording `served_at`. The date must fall on or before the `service_deadline` — the deadline day itself is timely — or the service is rejected with `ERR_NOTICE_DEADLINE_PASSED` (HTTP 409). A successful serve moves the notice `DRAFT` → `SERVED`, stamps `served_at` (null until this moment), freezes the deadline, and recomputes the project's `lien_posture`.

Delivery proof comes later, recorded by an `OpsAgent` as a `result` with an optional `proof_url` document. Proof can only be recorded on a notice whose `status` is `SERVED`; against any other state it fails with `ERR_NOTICE_NOT_SERVED` (HTTP 409). A `result` of `DELIVERED` moves the notice to `PROOF_CONFIRMED`, as does `REFUSED` when the effective rule's `refused_counts_as_served` is true. A `result` of `RETURNED` — or `REFUSED` when `refused_counts_as_served` is false — moves it to `DELIVERY_FAILED`. Either way, `proof_result` and `proof_url`, both null until proof is recorded, are set. Confirming proof decrements the project's and the company's `open_notice_count` by one and recomputes `lien_posture`; a failed delivery changes neither count, so the notice remains open.

A `DELIVERY_FAILED` notice is not dead: a `CustomerAdmin` can reprepare it, returning it to `DRAFT` with `served_at`, `proof_result`, and `proof_url` cleared and the `service_deadline` recomputed live against the currently effective rule. But a `DRAFT` notice whose `service_deadline` falls behind the logical clock auto-expires — lazily, on its next read or mutation — moving to `EXPIRED`, decrementing both open-notice counters, and recomputing the project's posture. The full state space of a notice order is `DRAFT`, `SERVED`, `PROOF_CONFIRMED`, `DELIVERY_FAILED`, and `EXPIRED`, with `PROOF_CONFIRMED` and `EXPIRED` terminal.

### 3.5. Lien Claims: Amounts, Locking, Filing, and Release

Liens exist only on private work. A `CustomerAdmin` creates a lien claim with just a `project_id`; on a `STATE_PUBLIC` or `FEDERAL_PUBLIC` project the create is rejected with `ERR_LIEN_NOT_PERMITTED_PUBLIC` (HTTP 422), and when the project already has an open claim — one in `DRAFT`, `AMOUNT_LOCKED`, or `FILED` — it is rejected with `ERR_OPEN_CLAIM_EXISTS` (HTTP 409). The claim is born in `DRAFT` with a computed `provisional_amount_cents`, and its reconciliation counters — `verified_paid_cents`, `effective_waiver_cents`, `waived_to_extras_cents`, and `waived_to_contract_cents` — are computed from the project's existing payments and waivers at creation (the verified-payment sum and the waiver waterfall), so they are zero only when the project has no verified payments and no effective waivers.

The provisional variant is deliberately simple: the project's `contract_value_cents` plus its `approved_extras_cents`, minus the sum of all recorded payments on the project whether `PENDING` or `VERIFIED`, minus the sum of all waivers that are not `VOIDED`, floored at zero. It ignores the retainage exclusion and the `cap_mode`, it counts conditional waivers unconditionally, and it is recomputed on every waiver or payment change while the claim remains `DRAFT` — so provisional and final figures can legitimately diverge for identical project data.

The final variant, computed at lock and maintained while the claim is `AMOUNT_LOCKED`, is the legally precise figure. Gross claimable value is the contract value plus approved extras, minus the `retainage_held_cents` — but that subtraction applies only when the rule's `retainage_claimable` is false; when retainage is claimable, nothing is subtracted. From gross, subtract verified payments — the sum of `amount_cents` over the project's payments in `VERIFIED` status, regardless of which claim they are allocated to — and then subtract effective waivers. An `APPLIED` waiver of type `UNCONDITIONAL_PROGRESS` or `UNCONDITIONAL_FINAL` always counts at its full `amount_cents`; a `CONDITIONAL_PROGRESS` or `CONDITIONAL_FINAL` waiver counts only when a `VERIFIED` payment exists on the project whose `received_at` falls on or after the waiver's `period_end`. When the rule's `cap_mode` is `UNCAPPED`, no cap applies; under `CONTRACT_BALANCE` the cap is the contract value minus verified payments, floored at zero. The `final_amount_cents` is the smaller of the cap and the remainder of gross minus verified payments minus effective waivers, floored at zero.

Locking also runs the waiver waterfall, which allocates the effective waivers against the project's two money pools. Effective waivers are processed in ascending `period_end` order, ties broken by ascending `created_at`. An extras pool starts at `approved_extras_cents` and a contract pool at `contract_value_cents`; each waiver consumes the smaller of its `amount_cents` and the remaining extras pool, then consumes the smaller of its own remainder and the remaining contract pool. The consumed portions are reported as `waived_to_extras_cents` (approved extras minus the remaining extras pool) and `waived_to_contract_cents` (contract value minus the remaining contract pool). Waiver credit is not capped by the pools: amounts exceeding both pools still count in full toward `effective_waiver_cents`.

Waivers enter through a `CustomerAdmin`, who records the `project_id`, the `waiver_type` — `CONDITIONAL_PROGRESS`, `UNCONDITIONAL_PROGRESS`, `CONDITIONAL_FINAL`, or `UNCONDITIONAL_FINAL` — the `amount_cents`, and the billing period as `period_start` and `period_end`. The amount must exceed zero (`ERR_AMOUNT_MUST_BE_POSITIVE`, HTTP 422), and the `period_end` must not be earlier than the `period_start` (a violation is rejected with `ERR_VALIDATION`, HTTP 400). Periods are half-open — each period includes its `period_start` and excludes its `period_end` — and a new waiver whose period overlaps a non-`VOIDED` waiver on the same project is rejected with `ERR_WAIVER_PERIOD_OVERLAP` (HTTP 409), while mere adjacency, where one waiver's `period_start` equals another's `period_end`, is allowed. A waiver is created `RECEIVED`; an `OpsAgent` applies it, moving it `RECEIVED` → `APPLIED` — applying a waiver in any other state fails with `ERR_WAIVER_NOT_RECEIVED` (HTTP 409) — and the project's open claim (whether `DRAFT` or `AMOUNT_LOCKED`) recomputes its waiver fields and amounts. A `CustomerAdmin` may void a waiver from either `RECEIVED` or `APPLIED`; voiding an applied waiver triggers a compensating recompute that restores the open claim's figures as if the waiver had never applied.

Payments flow the other direction. A `CustomerAdmin` records a payment with its `project_id`, an optional `lien_claim_id` allocation link used for outstanding-balance tracking, the `amount_cents` (which must exceed zero, else `ERR_AMOUNT_MUST_BE_POSITIVE`), and the `received_at` date; a `lien_claim_id` pointing at another project's claim is rejected with `ERR_PARTY_PROJECT_MISMATCH`. The payment starts `PENDING`, and verification is valid only while the payment is `PENDING`. Verification by an `OpsAgent` cascades: the project's open claim recomputes its `verified_paid_cents`, re-evaluates every conditional waiver's effectiveness — a newly verified payment may newly satisfy a waiver's condition — and, if the claim is `AMOUNT_LOCKED`, recomputes `final_amount_cents` and `outstanding_cents`; if the claim is `FILED`, only `outstanding_cents` is recomputed, since the filed amount is frozen.

A `CustomerAdmin` locks a `DRAFT` claim, moving it to `AMOUNT_LOCKED`. Two gates guard the lock: when the effective rule's `prelim_notice_required` is true, a notice order on the same project must already be `PROOF_CONFIRMED` (`ERR_PRELIM_NOTICE_REQUIRED`, HTTP 409), and the computed `final_amount_cents` must exceed zero (`ERR_ZERO_CLAIM_AMOUNT`, HTTP 422). When no published rule is effective for the project, no amount can be computed and the lock likewise fails with `ERR_ZERO_CLAIM_AMOUNT` (HTTP 422). Locking computes and pins everything the claim will need: `final_amount_cents`; `gross_snapshot_cents`, the gross claimable value as computed at lock; `locked_rule_id`, the identity of the effective rule; and `filing_window_end`, the `last_furnishing_date` plus the locked rule's `filing_window_days` in calendar days. The waterfall fields are computed at the same moment. Until it is locked, a claim carries null for `gross_snapshot_cents`, `filing_window_end`, `locked_rule_id`, and `outstanding_cents`.

Unlocking reverses the lock: a `CustomerAdmin` moves an `AMOUNT_LOCKED` claim back to `DRAFT`, clearing `final_amount_cents`, `gross_snapshot_cents`, `filing_window_end`, and `locked_rule_id`, and recomputing the provisional amount.

Recording the lien is an `OpsAgent` action carrying a `filed_at` date. Only an `AMOUNT_LOCKED` claim can be filed — any other state fails with `ERR_CLAIM_NOT_LOCKED` (HTTP 409) — and the `filed_at` must fall on or before the pinned `filing_window_end`, the last day inclusive, or the filing is rejected with `ERR_FILING_WINDOW_CLOSED` (HTTP 409). A successful filing moves the claim `AMOUNT_LOCKED` → `FILED`, stamps `filed_at` (null until this moment), freezes `final_amount_cents`, computes the previously null `foreclosure_deadline` as `filed_at` plus the locked rule's `foreclosure_deadline_days` calendar days, increments the project's `open_lien_count` by one, and recomputes the project's posture — a filed lien makes the project `ENCUMBERED`.

While `FILED`, the claim tracks `outstanding_cents`: the frozen `final_amount_cents` minus the sum of `VERIFIED` payments whose `lien_claim_id` names this claim. When a payment verification drives the outstanding balance to zero, the claim auto-releases, moving `FILED` → `RELEASED`. A `CustomerAdmin` may also release a `FILED` claim manually, for instance upon negotiated payment. Either way, release decrements the project's `open_lien_count` by one, recomputes the posture, and cancels every open foreclosure referral on the claim — those in `DRAFT`, `SENT`, `DECLINED`, or `ACCEPTED` — moving each to `CANCELLED` with `cancel_reason` `MOOT_RELEASED`.

A filed claim also accrues pre-judgment interest, computed on read for `FILED` and `FORECLOSED` claims and null otherwise. The base is the frozen `final_amount_cents`; the annual rate is the pinned rule's `interest_annual_rate`, increased by a tier bump of two percentage points (0.02) when the base strictly exceeds the tier threshold of 1,000,000 cents, and equal to the pinned rate otherwise — the tier test depends on the base alone, never on the total, which keeps the definition free of circularity. The day count runs from and including the `filed_at` day up to but excluding the earlier of the current clock date and the `foreclosure_deadline`; the deadline day itself is never counted, and a negative day count (a `filed_at` later than that endpoint) is floored at zero. The `interest_cents` is the base multiplied by the rate, multiplied by the day count, divided by 365, rounded half-up to whole cents, and the `total_with_interest_cents` is the base plus interest, capped at a maximum award of 1,000,000,000 cents; it remains null until the claim is filed.

A `FILED` claim whose `foreclosure_deadline` falls behind the logical clock — with no referral for the claim having reached `SUIT_FILED` — auto-expires, lazily, on its next read or mutation: the claim moves to `EXPIRED`, the project's `open_lien_count` decrements by one, the posture is recomputed, and open referrals are cancelled with `cancel_reason` `MOOT_EXPIRED`. Reading a claim, like reading a notice, applies any due expiry before the response is formed. The claim's full state space is `DRAFT`, `AMOUNT_LOCKED`, `FILED`, `RELEASED`, `BONDED_OFF`, `FORECLOSED`, and `EXPIRED`, the latter four being terminal.

### 3.6. Bonding Around a Lien and Foreclosure Referral

A claimant can free the property while preserving its security by bonding around a filed lien. A `CustomerAdmin` creates a bonding request with the `lien_claim_id` and a `surety_party_id`; the claim must be `FILED` (`ERR_CLAIM_NOT_FILED`, HTTP 409), the surety must be a `VERIFIED` party with `party_role` `SURETY` on the same project (`ERR_SURETY_NOT_VERIFIED`, HTTP 409; a surety from another project draws `ERR_PARTY_PROJECT_MISMATCH`), and no other bonding request may currently be `REQUESTED` for the claim (`ERR_OPEN_BONDING_EXISTS`, HTTP 409). The `bond_amount_cents` is computed at creation as the claim's frozen `final_amount_cents` multiplied by the pinned rule's `bond_pct`, rounded half-up to whole cents. The request starts `REQUESTED`.

An `OpsAgent` then records the bond with a `recorded_at` date — the request must still be `REQUESTED` (else `ERR_INVALID_STATE`, HTTP 409) and the linked claim still `FILED` (else `ERR_CLAIM_NOT_FILED`, HTTP 409) — moving the request to `BOND_RECORDED` and stamping `recorded_at` (null until the bond is recorded). Recording drives the claim itself from `FILED` to `BONDED_OFF`: the project's `open_lien_count` decrements by one, the posture recomputes, and every open referral on the claim is cancelled to `CANCELLED` with `cancel_reason` `MOOT_BONDED`. Alternatively, an `OpsAgent` may reject a `REQUESTED` bonding request, moving it to `REJECTED` with no further effects.

Foreclosure runs on a parallel track. A `CustomerAdmin` refers a `FILED` claim to counsel by creating a foreclosure referral with the `lien_claim_id` and a `counsel_name`; the claim must be `FILED` (`ERR_CLAIM_NOT_FILED`), no other open referral — one in `DRAFT`, `SENT`, `DECLINED`, or `ACCEPTED` — may exist for the claim (`ERR_OPEN_REFERRAL_EXISTS`, HTTP 409), and the clock must not have passed the claim's `foreclosure_deadline`, a gate that applies to creating a referral, sending it, and marking the suit filed alike (`ERR_FORECLOSURE_DEADLINE_PASSED`, HTTP 409). The referral starts `DRAFT`.

An `OpsAgent` sends the referral, moving it `DRAFT` → `SENT`. A `DECLINED` referral can be re-sent the same way, but only with a `counsel_name` that differs from the counsel who declined — a re-send that omits `counsel_name` or repeats the declined counsel is rejected with `ERR_VALIDATION` (HTTP 400); the recorded `counsel_name` is replaced with the new one. Counsel then responds with an `outcome`: a `SENT` referral becomes `ACCEPTED` or `DECLINED`. Finally, counsel marks the suit filed by recording `suit_filed_at`; the referral must be `ACCEPTED`, and the date must fall on or before the claim's `foreclosure_deadline` — the last day is inclusive — or the action fails with `ERR_FORECLOSURE_DEADLINE_PASSED`. Marking the suit filed moves the referral to `SUIT_FILED`, stamps `suit_filed_at` (null until the suit is filed), drives the linked claim from `FILED` to `FORECLOSED`, and turns the project's `lien_posture` to `LITIGATION`.

Whenever the linked claim leaves `FILED` through release, bonding-off, or expiry, every open referral on the claim — whether `DRAFT`, `SENT`, `DECLINED`, or `ACCEPTED` — is auto-cancelled to `CANCELLED`, its `cancel_reason` recording the claim's exit: `MOOT_RELEASED`, `MOOT_BONDED`, or `MOOT_EXPIRED`. A referral's `cancel_reason` is null unless it was auto-cancelled this way.

### 3.7. Public-Project Remedies: Stop Notices and Bond Claims

Public projects cannot be liened, so the platform offers the statutory substitutes. A stop notice demands that the public entity withhold funds. A `CustomerAdmin` creates one with the `project_id`, the demanded `amount_cents` (which must exceed zero, else `ERR_AMOUNT_MUST_BE_POSITIVE`), and the claimed coverage as `coverage_start` and `coverage_end` — a closed interval including both endpoints, with `coverage_end` never earlier than `coverage_start` (a violation is rejected with `ERR_VALIDATION`, HTTP 400). Only a `STATE_PUBLIC` project accepts a stop notice; any other project type is rejected with `ERR_STOP_NOTICE_NOT_PERMITTED` (HTTP 422). Coverage intervals must not collide: if the new notice's interval overlaps that of a `SERVED` stop notice on the same project — and sharing even a single boundary day counts as overlap — the request fails with `ERR_STOP_NOTICE_OVERLAP` (HTTP 409), a constraint evaluated when a stop notice is created and again when one is served. Creating the notice also requires an `ACTIVE` furnishing span for the project's deadline arithmetic (`ERR_NO_ACTIVE_SPAN`). The notice starts `DRAFT`.

An `OpsAgent` serves the notice by recording `served_at`, which must fall on or before the deadline — the `last_furnishing_date` plus the effective rule's `stop_notice_days`, last day inclusive — else `ERR_STOP_NOTICE_DEADLINE_PASSED` (HTTP 409). Serving moves the notice `DRAFT` → `SERVED`, stamps `served_at`, and recomputes the posture, which a served stop notice pushes to `ENCUMBERED`. An `OpsAgent` may later release a `SERVED` notice, moving it to `RELEASED` with the posture recomputed. A `DRAFT` notice whose deadline falls behind the logical clock auto-expires to `EXPIRED`, lazily, on its next read or mutation.

A bond claim pursues the payment bond instead of the property. A `CustomerAdmin` creates one with the `project_id`, a `surety_party_id`, and the claimed `amount_cents` (again, positive or `ERR_AMOUNT_MUST_BE_POSITIVE`). The project must be `STATE_PUBLIC` or `FEDERAL_PUBLIC`; private projects are rejected with `ERR_BOND_CLAIM_NOT_PERMITTED` (HTTP 422). The surety must be a `VERIFIED` `SURETY` on the same project, else `ERR_SURETY_NOT_VERIFIED` or `ERR_PARTY_PROJECT_MISMATCH`. The claim starts `DRAFT`.

An `OpsAgent` submits the claim to the surety by recording `submitted_at`, timely when on or before the `last_furnishing_date` plus the effective rule's `bond_claim_days` — last day inclusive — else `ERR_BOND_CLAIM_DEADLINE_PASSED` (HTTP 409). Submission moves the claim `DRAFT` → `SUBMITTED`, stamps `submitted_at` (null until submission), and recomputes the posture, which a submitted bond claim pushes to `ENCUMBERED`. An `OpsAgent` later resolves a `SUBMITTED` claim with an `outcome`: the claim becomes `PAID` or `DENIED`, the `resolve_outcome` — null until resolution — is recorded accordingly, and the posture is recomputed. A `DRAFT` bond claim past its deadline auto-expires to `EXPIRED`, lazily, on its next read or mutation.

## 4. Endpoint Definitions

Operations that create new resources return a `201 Created` status code. Operations that modify an existing resource, and all reads, return a `200 OK` status code. In the table below, "All roles" means all four roles of §2.1 — `PlatformAdmin`, `OpsAgent`, `CustomerAdmin`, and `Counsel`; `CustomerAdmin` access remains company-scoped per §2.1. Request bodies, computed fields, and side effects are defined by the narratives of §3 rather than duplicated here.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/lien/companies` | Create a claimant company | PlatformAdmin |
| GET | `/lien/companies/{id}` | Get a company | All roles |
| POST | `/lien/companies/{id}/balance-adjustments` | Adjust (credit or debit) a company's prepaid balance; OCC-guarded | PlatformAdmin |
| GET | `/lien/companies/{id}/projects` | List projects owned by a company | All roles |
| POST | `/lien/jurisdiction-rules` | Publish the first rule for a (state_code, project_type) pair | PlatformAdmin |
| POST | `/lien/jurisdiction-rules/{id}/supersede` | Publish a successor rule, superseding the addressed PUBLISHED rule; OCC-guarded | PlatformAdmin |
| GET | `/lien/jurisdiction-rules/{id}` | Get a jurisdiction rule | All roles |
| GET | `/lien/jurisdiction-rules/{id}/successors` | List rules that supersede this rule | All roles |
| GET | `/lien/jurisdiction-rules/{id}/lien-claims` | List lien claims that pinned this rule at lock | All roles |
| POST | `/lien/projects` | Create a project for the caller's company | CustomerAdmin |
| GET | `/lien/projects/{id}` | Get a project | All roles |
| POST | `/lien/projects/{id}/research-advance` | Advance research UNRESEARCHED → RESEARCHED → VERIFIED | OpsAgent |
| GET | `/lien/projects/{id}/deadline-calendar` | Computed deadline projection across the project's jurisdiction | All roles |
| GET | `/lien/projects/{id}/parties` | List parties of a project | All roles |
| GET | `/lien/projects/{id}/furnishing-spans` | List furnishing spans of a project | All roles |
| GET | `/lien/projects/{id}/notices` | List notice orders of a project | All roles |
| GET | `/lien/projects/{id}/lien-claims` | List lien claims of a project | All roles |
| GET | `/lien/projects/{id}/waivers` | List waivers of a project | All roles |
| GET | `/lien/projects/{id}/payments` | List payments of a project | All roles |
| GET | `/lien/projects/{id}/stop-notices` | List stop notices of a project | All roles |
| GET | `/lien/projects/{id}/bond-claims` | List bond claims of a project | All roles |
| POST | `/lien/parties` | Add a researched party to a project | CustomerAdmin |
| GET | `/lien/parties/{id}` | Get a party | All roles |
| POST | `/lien/parties/{id}/decide` | Verify or fail a party's research | OpsAgent |
| GET | `/lien/parties/{id}/notices` | List notice orders addressed to this party | All roles |
| GET | `/lien/parties/{id}/bonding-requests` | List bonding requests naming this party as surety | All roles |
| GET | `/lien/parties/{id}/bond-claims` | List bond claims naming this party as surety | All roles |
| POST | `/lien/furnishing-spans` | Record a furnishing span, superseding the prior ACTIVE span of the same kind; OCC-guarded | CustomerAdmin |
| POST | `/lien/notices` | Order a preliminary notice; quotes the fee and debits the company balance | CustomerAdmin |
| GET | `/lien/notices/{id}` | Get a notice order (applies due lazy expiry first) | All roles |
| POST | `/lien/notices/{id}/serve` | Mark a DRAFT notice served | OpsAgent |
| POST | `/lien/notices/{id}/proof` | Record delivery proof on a SERVED notice | OpsAgent |
| POST | `/lien/notices/{id}/reprepare` | Return a DELIVERY_FAILED notice to DRAFT for re-service | CustomerAdmin |
| POST | `/lien/lien-claims` | Create a lien claim in DRAFT with a provisional amount | CustomerAdmin |
| GET | `/lien/lien-claims/{id}` | Get a lien claim (applies due lazy expiry first) | All roles |
| POST | `/lien/lien-claims/{id}/lock` | Lock the claim amount, pinning the effective rule | CustomerAdmin |
| POST | `/lien/lien-claims/{id}/unlock` | Unlock the claim back to DRAFT | CustomerAdmin |
| POST | `/lien/lien-claims/{id}/file` | Record the lien with the county | OpsAgent |
| POST | `/lien/lien-claims/{id}/release` | Release a FILED lien | CustomerAdmin |
| GET | `/lien/lien-claims/{id}/payments` | List payments allocated to this claim | All roles |
| GET | `/lien/lien-claims/{id}/bonding-requests` | List bonding requests for this claim | All roles |
| GET | `/lien/lien-claims/{id}/foreclosure-referrals` | List foreclosure referrals for this claim | All roles |
| POST | `/lien/waivers` | Record a lien waiver | CustomerAdmin |
| POST | `/lien/waivers/{id}/apply` | Apply a RECEIVED waiver against the claim amount | OpsAgent |
| POST | `/lien/waivers/{id}/void` | Void a waiver, with compensating recompute when it was APPLIED | CustomerAdmin |
| POST | `/lien/payments` | Record a payment against a project, optionally allocated to a claim | CustomerAdmin |
| POST | `/lien/payments/{id}/verify` | Verify a payment; cascades into claim amounts and may auto-release a FILED claim | OpsAgent |
| POST | `/lien/bonding-requests` | Request bonding around a FILED lien | CustomerAdmin |
| POST | `/lien/bonding-requests/{id}/record` | Record the bond; the linked lien becomes BONDED_OFF | OpsAgent |
| POST | `/lien/bonding-requests/{id}/reject` | Reject a bonding request | OpsAgent |
| POST | `/lien/foreclosure-referrals` | Refer a FILED lien to foreclosure counsel | CustomerAdmin |
| POST | `/lien/foreclosure-referrals/{id}/send` | Send the referral to counsel (from DRAFT, or from DECLINED with a new counsel) | OpsAgent |
| POST | `/lien/foreclosure-referrals/{id}/respond` | Counsel accepts or declines the referral | Counsel |
| POST | `/lien/foreclosure-referrals/{id}/mark-suit-filed` | Counsel marks the foreclosure suit filed; the lien becomes FORECLOSED | Counsel |
| POST | `/lien/stop-notices` | Create a stop notice (STATE_PUBLIC projects only) | CustomerAdmin |
| POST | `/lien/stop-notices/{id}/serve` | Serve a stop notice within its deadline | OpsAgent |
| POST | `/lien/stop-notices/{id}/release` | Release a SERVED stop notice | OpsAgent |
| POST | `/lien/bond-claims` | Create a payment-bond claim (public projects only) | CustomerAdmin |
| POST | `/lien/bond-claims/{id}/submit` | Submit a bond claim to the surety within its deadline | OpsAgent |
| POST | `/lien/bond-claims/{id}/resolve` | Resolve a submitted bond claim as PAID or DENIED | OpsAgent |
| POST | `/_clock/set_current_utc` | Set the logical clock (ISO 8601 UTC) | PlatformAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error are defined in the narratives of §2 and §3; this catalogue fixes only the identifiers and their HTTP status codes.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_VALIDATION` | 400 Bad Request |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_RESEARCH_ALREADY_VERIFIED` | 409 Conflict |
| `ERR_PARTIES_UNVERIFIED` | 409 Conflict |
| `ERR_PROJECT_NOT_VERIFIED` | 409 Conflict |
| `ERR_PARTY_NOT_VERIFIED` | 409 Conflict |
| `ERR_SURETY_NOT_VERIFIED` | 409 Conflict |
| `ERR_PARTY_PROJECT_MISMATCH` | 422 Unprocessable Entity |
| `ERR_DELIVERY_METHOD_NOT_ALLOWED` | 422 Unprocessable Entity |
| `ERR_NO_ACTIVE_SPAN` | 409 Conflict |
| `ERR_NOTICE_DEADLINE_PASSED` | 409 Conflict |
| `ERR_NOTICE_NOT_SERVED` | 409 Conflict |
| `ERR_LIEN_NOT_PERMITTED_PUBLIC` | 422 Unprocessable Entity |
| `ERR_OPEN_CLAIM_EXISTS` | 409 Conflict |
| `ERR_PRELIM_NOTICE_REQUIRED` | 409 Conflict |
| `ERR_ZERO_CLAIM_AMOUNT` | 422 Unprocessable Entity |
| `ERR_CLAIM_NOT_LOCKED` | 409 Conflict |
| `ERR_CLAIM_NOT_FILED` | 409 Conflict |
| `ERR_FILING_WINDOW_CLOSED` | 409 Conflict |
| `ERR_WAIVER_PERIOD_OVERLAP` | 409 Conflict |
| `ERR_WAIVER_NOT_RECEIVED` | 409 Conflict |
| `ERR_STOP_NOTICE_NOT_PERMITTED` | 422 Unprocessable Entity |
| `ERR_STOP_NOTICE_OVERLAP` | 409 Conflict |
| `ERR_STOP_NOTICE_DEADLINE_PASSED` | 409 Conflict |
| `ERR_BOND_CLAIM_NOT_PERMITTED` | 422 Unprocessable Entity |
| `ERR_BOND_CLAIM_DEADLINE_PASSED` | 409 Conflict |
| `ERR_OPEN_BONDING_EXISTS` | 409 Conflict |
| `ERR_OPEN_REFERRAL_EXISTS` | 409 Conflict |
| `ERR_FORECLOSURE_DEADLINE_PASSED` | 409 Conflict |
| `ERR_RULE_ALREADY_PUBLISHED` | 409 Conflict |
| `ERR_RULE_NOT_PUBLISHED` | 409 Conflict |
| `ERR_INSUFFICIENT_BALANCE` | 402 Payment Required |
| `ERR_AMOUNT_MUST_BE_POSITIVE` | 422 Unprocessable Entity |
| `ERR_SPAN_DATES_INVALID` | 422 Unprocessable Entity |
