# Corporate Litigation Matters API — Product Requirements Document

## 1. Introduction

In-house litigation departments run dozens of disputes at once, each carrying financial exposure that Finance must reserve against, outside counsel whose rates and conflicts must be vetted, preservation duties that must be provably acknowledged, and settlement decisions that escalate through a strict authority hierarchy. Today these concerns live in spreadsheets and email threads, which makes it impossible to answer basic questions — What is our open exposure? Which matters are frozen and why? Who approved this settlement? — with any auditability. This document specifies the Corporate Litigation Matters API, mounted under `/litigation`, which manages the full life of a litigated matter from intake through resolution and closure.

The API is built around the **Matter** as the central aggregate. Around it orbit budgets and accrual entries that feed an append-only spend ledger, litigation holds and their custodians, discovery vendors and their work orders, a court-calendar of deadlines, settlement requests with a negotiation cycle, and payment requests with a two-dimensional lifecycle. Two design commitments shape everything that follows. First, money is tracked in integer cents with deterministic floor division, so a reserve or a utilization percentage computed by two different clients always agrees to the cent. Second, every guard — segregation of duties, settlement authority routing, vendor clearance, posture gating — is enforced by the server against the logical clock and the recorded state of the matter, never assumed from client behavior.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide contract: authentication, response envelopes, pagination, resource identity, arithmetic precision, the logical clock, concurrency control, duty segregation, the matter posture ladder, reference validation, and the fixed order in which validations are evaluated.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the capacity in which they act. A request with a missing or malformed header, or whose `X-User-Role` does not name one of the declared roles, is rejected with `ERR_UNAUTHENTICATED`. A request whose role is not in the endpoint's authorized list is rejected with `ERR_FORBIDDEN_ROLE`.

The system recognizes exactly eight roles. `LitigationCounsel` is the in-house counsel who owns the day-to-day conduct of assigned matters. `DeputyGeneralCounsel` is the second-in-command, approving engagements, reopening matters, and countering settlement requests. `GeneralCounsel` is the chief legal officer, governing the outside-counsel panel and executing settlements. `ChiefFinancialOfficer` is an executive approver designated for high-tier settlements. `BoardCommittee` is the board litigation committee, the final approval authority for the largest exposures. `LegalOperationsAnalyst` administers staff, firms, vendors, work orders, the logical clock, and matter closure. `FinanceBusinessPartner` approves budgets, posts accruals, and runs payment approval and disbursement. `StaffUser` is any staff member acting in their own capacity, used solely for self-acknowledgement of hold-custodian notices.

Identity is bound to the staff directory for seven of the eight roles. When `X-User-Role` is `LitigationCounsel`, `DeputyGeneralCounsel`, `GeneralCounsel`, `ChiefFinancialOfficer`, `LegalOperationsAnalyst`, `FinanceBusinessPartner`, or `StaffUser`, `X-User-ID` is the `id` of the acting StaffUser; ownership checks on any resource that references a staff user — a matter's `owning_counsel_id`, a budget's `submitted_by_user_id`, a custodian's `staff_user_id`, and so on — compare the resource's foreign-key field to `X-User-ID`. The server never looks `X-User-ID` up in the staff directory: an id that names no existing staff record is still accepted, and every ownership-style check is a plain equality comparison against the id recorded on the resource. Correspondingly, where a workflow narrative names "the owning counsel" as the actor of an operation, that phrase names the typical actor only; a personal identity gate applies solely where the narrative explicitly declares one — assessment submission, advancement to staffing, activation, and resolution of a matter, settlement submission, counter acceptance, post-submission settlement withdrawal, custodian self-acknowledgement, and cancellation of a submitted payment request. When `X-User-Role` is `BoardCommittee`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, as an entry of `approved_by_user_ids` on a settlement approval) but never compares it to any entity's `id`.

A staff member's `job_family` — one of `LEGAL`, `FINANCE`, `OPERATIONS`, or `EXECUTIVE` — is a descriptive label of the functional family they belong to; it is recorded for directory purposes only, and the server does not enforce any job-family-to-role mapping. A deactivated staff member (`is_active` false) may not own new matters or be named as a hold custodian.

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

Requests to paths the API does not define, and requests using an unsupported method on a defined path, are both rejected with `ERR_NOT_FOUND` (404); an unexpected server failure is surfaced as `ERR_INVALID_REQUEST` (400).

### 2.3. Pagination

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned: it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips that many items from the start of the result set and defaults to 0. A `limit` or `offset` value that does not parse as an integer is rejected with `ERR_INVALID_REQUEST`; an integer outside the allowed range is clamped into it (`limit` into [1, 100], `offset` to at least 0) rather than rejected. Unless an endpoint states otherwise, list results are sorted in creation order (`created_at` ascending, ties broken by creation sequence); the matter calendar list is the documented exception and sorts by due date, ties again broken by creation sequence (see §3.7). Filter parameters are exact-match equality tests on the named field and combine conjunctively; a filter on a boolean field accepts a case-insensitive `true` or `false`, and any other value leaves that filter unused. Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope, where `has_more` is true exactly when `offset` plus the size of the returned page is less than `total_count`.

### 2.4. Resource Identity and Change Tracking

Every primary resource carries a standard set of system-managed properties. The `id` is a server-minted UUID with no type prefix. `created_at` is an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created. `updated_at` is the same kind of timestamp, refreshed on every mutation. `version` is an integer that starts at 1 on creation and increments by exactly one on every mutation of the resource — including mutations caused by cascades and by recomputation of derived fields, so a matter whose reserve is recomputed after an accrual posts has both a fresh `updated_at` and a higher `version` than before.

One entity breaks this pattern deliberately: the AccrualEntry is an append-only ledger row and carries only `id` and `created_at`. It has no `updated_at` and no `version`; ledger rows are never edited in place, only reversed by compensating entries (see §3.4).

### 2.5. Money, Integer Arithmetic, and Rounding

All monetary amounts in this API — exposures, reserves, budgets, rates, settlement amounts, payments — are integers denominated in USD cents. There are no floating-point amounts anywhere in the system. Every division performed as part of a calculation uses floor division (the result is rounded toward negative infinity to a whole number of cents or percent), and where a computed value could go negative it is floored at zero. Percentage fields such as `probability_of_loss_pct` and `utilization_pct` are likewise integers. Where a calculation applies a discounted rate tier by tier — the vendor work-order cost is the one such calculation — floor division is applied per tier before the tier subtotals are summed, never once at the end.

### 2.6. The Logical Clock and System Sweeps

All time-sensitive rules in the system — deadline misses, settlement offer expiries, escalation cooling periods, work-order start gates — read a single logical clock, never the server's wall clock. At startup the logical clock reads exactly `2026-08-01T00:00:00Z`; until it is explicitly set it returns that instant and never falls back to wall-clock time. A `LegalOperationsAnalyst` advances the clock through an operations-only capability that accepts a `to_iso8601` instant and answers with the resulting `current_utc`. Datetime inputs throughout the API are ISO 8601 strings; a value without an offset is read as UTC, and a date-only form is read as midnight UTC that day. The clock setter accepts any parseable instant — earlier or later than the current reading; no monotonicity check is applied. Every state-transition stamp the system records (a hold's `issued_at` and `released_at`, a custodian's `noticed_at` and `acknowledged_at`, a deadline's `completed_at`, a matter's `resolved_at`, a payment's `disbursed_at`, an accrual entry's `submitted_at`) is taken from the logical clock, and all such logical-clock-stamped values — as well as client-supplied datetimes echoed back on reads, such as `filing_date`, `due_at`, `scheduled_start`, `scheduled_end`, and `expires_at`, and the `current_utc` answer itself — are rendered in ISO 8601 UTC with a three-digit fractional part included only when it is non-zero, so a whole-second instant renders as `2026-08-01T00:00:00Z`.

Advancing the clock fires three system sweeps, always in this pinned order. First, every Deadline still `SCHEDULED` whose `due_at` is earlier than the new clock time transitions to `MISSED`. Second, every Deadline still `MISSED` whose `due_at` is more than 30 days behind the new clock time transitions to `EXPIRED`. Third, every SettlementRequest in `SUBMITTED`, `UNDER_REVIEW`, or `COUNTERED` whose `expires_at` is earlier than the new clock time transitions to `EXPIRED`. Each transition a sweep fires reapplies that transition's full side effects — most significantly, a jurisdictional deadline swept into `MISSED` freezes its matter's posture exactly as a manual miss would. The `MISSED` → `EXPIRED` deadline transition has no posture side effect of its own, and a settlement request swept to `EXPIRED` clears any recorded counter amount alongside the recorded approvals.

### 2.7. Version-Guarded Writes on the Matter

Two create endpoints are guarded by optimistic concurrency control on the parent Matter, because both anchor long-lived financial or legal commitments to the client's view of the matter. Creating a budget for a matter and creating a settlement request for a matter each require the request body to carry `expected_matter_version`, a non-optional field holding the matter's `version` as the client last observed it. If another writer has advanced the matter's version since that observation — for example by having a budget approved, which supersedes the chain head the client assumed, or by submitting a settlement that re-pins the authority tier — the supplied value will not match the matter's current `version`, and the create is rejected with `ERR_STALE_MATTER_VERSION` (HTTP 412). Both of these creates, when they succeed, themselves increment the matter's `version` by one, so two clients holding the same observed version cannot both succeed. No other endpoint accepts a version field.

### 2.8. Segregation of Duties

Approvals in this system are worthless if the same person can request and approve. Four approval actions therefore enforce segregation of duties, and a breach of any of them is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). A budget may not be approved by the user recorded as its `submitted_by_user_id`. A payment request may not be finance-approved by the user recorded as its `submitted_by_user_id`. A settlement request may not be approved by its `requested_by_user_id`, nor by any user already present in its `approved_by_user_ids` — a second approval must come from a different person than the first. And for an engagement whose `role_type` is `LEAD_COUNSEL`, the approver must not be the matter's `owning_counsel_id`, since the owning counsel is considered the proposer of the staffing request.

### 2.9. The Matter Posture Ladder

Every matter carries a derived `posture` — one of `OPEN`, `RESTRICTED`, or `FROZEN` — that gates child operations across the whole system. The posture is recomputed on every matter state transition, whenever budget utilization crosses a threshold, and whenever a jurisdictional deadline is missed or vacated. Its evaluation is a precedence ladder, checked top to bottom with the first matching rung winning:

1. If any deadline of the matter has `is_jurisdictional` true and status `MISSED`, the posture is `FROZEN` — the jurisdictional freeze beats everything else.
2. Otherwise, if the matter's `status` is `RESOLVED` or `CLOSED`, the posture is `FROZEN`.
3. Otherwise, if the matter's `status` is `INTAKE`, `ASSESSMENT`, or `SETTLEMENT_PENDING`, the posture is `RESTRICTED`.
4. Otherwise, if an `APPROVED` budget exists for the matter and its `utilization_pct` is at least 100, the posture is `FROZEN`.
5. Otherwise, if an `APPROVED` budget exists and its `utilization_pct` is at least 90, the posture is `RESTRICTED` — utilization of exactly 90 triggers this rung.
6. Otherwise the posture is `OPEN`.

The gates themselves are uniform: a `FROZEN` posture blocks accrual submission, work-order start, hold issuance, and settlement submission; a posture of `RESTRICTED` or `FROZEN` blocks work-order authorization, because authorizing new vendor spend on a restricted matter is precisely the leak the ladder exists to close. An operation refused by this gate is rejected with `ERR_MATTER_POSTURE_FROZEN` (HTTP 409).

### 2.10. Nested Paths and Reference Integrity

Endpoints that address a resource through a parent path validate identifiers strictly left to right. On a matter-scoped path, the matter's existence is checked before any child identifier is consulted; the first identifier in the path that does not correspond to an existing resource yields `ERR_NOT_FOUND` (HTTP 404), and later identifiers are not examined. Separately, identifiers carried in the request body — `firm_id`, `vendor_id`, `hold_id`, `settlement_request_id`, staff user ids, and the self-referential `supersedes_engagement_id`, `prior_version_id`, and `reverses_entry_id` — must each name an existing resource, or the request fails with `ERR_REFERENCE_NOT_FOUND` (HTTP 404).

Existence is not enough for references that cross aggregate boundaries. A work order's `hold_id` must name a hold belonging to the same matter; a payment's `settlement_request_id` must name a settlement of the same matter; a revised budget's `prior_version_id` must name a budget of the same matter; an engagement's `supersedes_engagement_id` must name an engagement of the same matter. A reference that exists but belongs to a different matter — or, in the work-order case, a hold of the right matter that is not in `ISSUED` or `ACKNOWLEDGED` — is rejected with `ERR_CROSS_REFERENCE_MISMATCH` (HTTP 422).

### 2.11. Validation Evaluation Order

When a request could fail several checks at once, the server evaluates validations in a fixed priority order and reports the first failure encountered; clients can rely on this order to understand which problem to fix first. The order is: (1) authentication of the `X-User-Role` and `X-User-ID` headers (`ERR_UNAUTHENTICATED`); (2) whether the acting role is permitted on the endpoint (`ERR_FORBIDDEN_ROLE`); (3) left-to-right existence of path-templated resources (`ERR_NOT_FOUND`); (4) existence of body-referenced foreign keys (`ERR_REFERENCE_NOT_FOUND`); (5) whether the invoked transition exists from the target resource's current state (`ERR_INVALID_STATE`); (6) matter-ownership where the transition requires the owning counsel (`ERR_NOT_MATTER_OWNER`); (7) segregation of duties (`ERR_SEGREGATION_OF_DUTIES`); (8) hold-compliance pins on release, resolve, and close (`ERR_HOLD_COMPLIANCE_BLOCK`); (9) posture gates (`ERR_MATTER_POSTURE_FROZEN`); (10) vendor clearance sufficiency (`ERR_VENDOR_CLEARANCE_INSUFFICIENT`); (11) scalar field constraints (`ERR_FIELD_CONSTRAINT`); (12) uniqueness (`ERR_DUPLICATE`); (13) schedule conflicts and cooling periods (`ERR_SCHEDULE_CONFLICT`); (14) deadline timing (`ERR_DEADLINE_TIMING`); (15) cross-matter reference integrity (`ERR_CROSS_REFERENCE_MISMATCH`); (16) referenced-entity state (`ERR_REFERENCE_STATE_INVALID`); (17) the engagement rate cap (`ERR_RATE_CAP_EXCEEDED`); (18) vendor capacity (`ERR_VENDOR_CAPACITY_EXCEEDED`); (19) settlement authority routing (`ERR_SETTLEMENT_AUTHORITY`); (20) budget fiscal gates (`ERR_BUDGET_EXCEEDED`); (21) required approved-budget presence (`ERR_NO_APPROVED_BUDGET`); (22) stale matter version (`ERR_STALE_MATTER_VERSION`); and (23) request-shape well-formedness (`ERR_INVALID_REQUEST`).

Request-shape checking at step 23 is strict: a missing required field, an empty string where a non-empty value is required, a malformed scalar type, or any field not declared in the endpoint's input list — explicitly including computed or system-managed fields such as `posture`, `exposure_tier`, `accrued_to_date_cents`, `id`, or `version` sent by a client — is rejected with `ERR_INVALID_REQUEST` (HTTP 400). An absent or syntactically unparseable JSON request body is treated as an empty object, so its fate is decided by the required-field rules of step 23. After all twenty-three general checks come the endpoint-specific state preconditions, in this relative order: (24) the executed engagement letter (`ERR_ENGAGEMENT_LETTER_REQUIRED`); (25) the active-engagement requirement on matter activation (`ERR_NO_ACTIVE_ENGAGEMENT`); (26) open limitation exposure on matter resolution (`ERR_OPEN_LIMITATION_EXPOSURE`); (27) custodian self-acknowledgement (`ERR_CUSTODIAN_SELF_ACK_REQUIRED`); (28) the confirmed-payment reopen block (`ERR_REOPEN_BLOCKED_BY_CONFIRMED_PAYMENT`); and (29) payment-rail state (`ERR_PAYMENT_RAIL_STATE`). On a small set of endpoints the endpoint-specific precondition is evaluated before the step-23 request-shape check rather than after it: engagement activation (check 24), matter activation (check 25), custodian self-acknowledgement (check 27), and the payment-rail actions disburse, confirm-receipt, mark-returned, and redisburse (check 29); likewise the matter intake update (`PATCH /litigation/matters/{id}`) evaluates its frozen-state check (5) before body-reference existence (4). Everywhere else the published order holds exactly.

## 3. Business Logic & Workflows

### 3.1. Matter Intake and Exposure Assessment

Before any matter can be opened, the staff directory must exist. A `LegalOperationsAnalyst` registers each staff user with a `full_name`, a corporate `email` (unique across the directory — a duplicate is rejected with `ERR_DUPLICATE`), a `job_family`, and an optional `is_active` flag that defaults to true. The directory can be listed with optional `email` and `job_family` filters, and individual staff records fetched by id.

A `LitigationCounsel` opens a matter by supplying a `title`, a `matter_type` — one of `COMMERCIAL`, `EMPLOYMENT`, `IP`, `REGULATORY`, `PRODUCT_LIABILITY`, or `CLASS_ACTION` — the `adverse_party`, a free-text `jurisdiction` identifying the court or forum, the `filing_date` on which the complaint was filed or threatened, and the `owning_counsel_id` of the staff member who will own day-to-day conduct. The new matter starts in `INTAKE` with `accrued_to_date_cents` initialized to zero and its posture computed fresh. The server mints a `matter_number` for display: the literal prefix `MTR-`, the four-digit year read from the logical clock at creation, and a six-digit sequence assigned in creation order. The matter number is identity only and is never used in ranking or allocation of any kind.

The exposure triplet — `exposure_low_cents`, `exposure_high_cents`, and `probability_of_loss_pct` — may be supplied at intake or patched in afterwards. The low end must be at least zero; the high end must be greater than or equal to the low end; the probability of loss is an integer percent between 0 and 100 inclusive. A value violating any of these shapes, or an enum outside its declared set, is rejected with `ERR_FIELD_CONSTRAINT`. While the matter remains in `INTAKE` or `ASSESSMENT`, the owning counsel may update the `title`, any of the three exposure fields, or the `owning_counsel_id`; every such update recomputes the tier, reserve, and posture and increments the matter's `version`. Once the matter has advanced past `ASSESSMENT`, the exposure triplet is frozen and the update call is rejected with `ERR_INVALID_STATE`.

From the triplet the server derives the matter's `exposure_tier`, the classification that later drives settlement approval routing. For most matter types the expected loss in cents is the sum of `exposure_low_cents` and `exposure_high_cents`, multiplied by `probability_of_loss_pct`, divided by two hundred with floor division. An expected loss strictly below 25,000,000 cents (two hundred fifty thousand dollars) lands in `TIER_1`; below 100,000,000 cents in `TIER_2`; below 500,000,000 cents in `TIER_3`; anything at or above that in `TIER_4`. Because the boundary test is a strict less-than, an expected loss of exactly 25,000,000 cents classifies as `TIER_2`, not `TIER_1`. Two matter types get a deliberately more conservative reading: for a `CLASS_ACTION` or `REGULATORY` matter the expected loss is computed from the high end of the range alone — `exposure_high_cents` multiplied by `probability_of_loss_pct`, divided by one hundred with floor division — so such a matter tiers strictly higher than a `COMMERCIAL` matter with identical numbers. The classification recomputes on matter creation when the triplet is present, on every update to any exposure field, and on reopen. Until all three exposure fields are present, `exposure_tier` — and with it `reserve_amount_cents`, which is derived from the tier — remains null.

The second derived figure is the accounting reserve, `reserve_amount_cents`. Its evaluation order is pinned. First a base is read from the tier table: 500,000 cents for `TIER_1`, 2,500,000 for `TIER_2`, 10,000,000 for `TIER_3`, and 50,000,000 for `TIER_4`. Second, the base is scaled by probability: multiplied by `probability_of_loss_pct` and divided by one hundred with floor division. Third, the matter's `accrued_to_date_cents` is subtracted, and fourth, the result is floored at zero. Any variant adjustment — the resolution and reopen variants described in §3.9 — applies last, after this base computation. The reserve recomputes whenever the tier recomputes, whenever an accrual entry posts or is voided, and at resolution and reopen.

Submitting the assessment moves the matter from `INTAKE` to `ASSESSMENT`. The transition requires that all three exposure fields are set and that the high end is at least the low end, and it is owner-gated: the acting user's `X-User-ID` must equal the matter's `owning_counsel_id`, failing which the call is rejected with `ERR_NOT_MATTER_OWNER`. Submission recomputes the tier, the reserve, and the posture, and increments the matter's `version`. The matters list supports optional `status`, `exposure_tier`, `matter_type`, and `owning_counsel_id` filters, and fetching a single matter returns the computed `exposure_tier`, `reserve_amount_cents`, `accrued_to_date_cents`, and `posture` alongside the intake fields.

### 3.2. Seeding the Calendar, Budgeting, and the Road to Activation

A matter in `ASSESSMENT` cannot advance until its calendar exists. The owning counsel seeds it by creating deadlines, each carrying a `deadline_type` — `COURT_DEADLINE`, `HEARING`, `DISCOVERY_CUTOFF`, `FILING`, `INTERNAL_REVIEW`, or `LIMITATION_EXPIRY` — a short `title`, the `due_at` instant, an optional `is_jurisdictional` flag defaulting to false, and an optional `reminder_days` count, at least zero and defaulting to 7, marking how many days before `due_at` the entry should be flagged at risk. New deadlines start `SCHEDULED`. Advancing to `STAFFING` then requires that at least one deadline exists for the matter — failing which the advance is rejected with `ERR_INVALID_STATE` — and is owner-gated; the transition recomputes the posture and increments the matter's `version`.

Budgeting runs in parallel with staffing. The owning counsel drafts a budget with a `fiscal_year`, a `lifecycle_budget_cents` authorizing total spend over the life of the matter, and an `fy_budget_cents` authorizing spend within that fiscal year; both amounts must be positive and the fiscal-year amount must not exceed the lifecycle amount, failing which the create is rejected with `ERR_FIELD_CONSTRAINT`. Because the create is version-guarded per §2.7, the body must also carry `expected_matter_version`. A revised budget carries `prior_version_id` pointing at the budget it supersedes — the chain head is the original — and that reference must name a budget of the same matter or the create fails with `ERR_CROSS_REFERENCE_MISMATCH`. Every successful budget create increments the matter's `version`, and at most one budget per matter is ever `APPROVED` at a time.

A draft budget moves `DRAFT` → `SUBMITTED` at the hands of the owning counsel while the matter is in `ASSESSMENT`, `STAFFING`, `ACTIVE`, or `REOPENED`; the submission stamps `submitted_by_user_id`. Approval belongs to a `FinanceBusinessPartner`, who may not be the submitter, and who faces two further fiscal gates: no other budget for the same matter may already be `APPROVED` — where the budget named by this budget's `prior_version_id`, being about to be superseded, does not count against that unique-active invariant — and `fy_budget_cents` must be at least the matter's current `accrued_to_date_cents`, since the system will not approve a budget already exceeded by posted accruals. Breaching either fiscal gate yields `ERR_BUDGET_EXCEEDED`; passing them moves the budget `SUBMITTED` → `APPROVED`, stamps `approved_by_user_id`, supersedes the referenced prior version (`APPROVED` → `SUPERSEDED`, a cascade that increments the old budget's `version`), and computes the budget's `utilization_pct`. A submitted budget may instead be rejected, moving `SUBMITTED` → `REJECTED`. Utilization is the matter's accrued spend as a percentage of the fiscal-year budget: `accrued_to_date_cents` multiplied by 100, divided by `fy_budget_cents`, floored to a whole percent — so 89,999 cents accrued against a 100,000-cent budget reads 89, not 90. Budget lists support `status` filters within a matter, and the cross-matter budget list supports `matter_id`, `submitted_by_user_id`, `approved_by_user_id`, `prior_version_id`, and `status` filters for audit.

Activation is the gateway to real work. From `STAFFING`, activation to `ACTIVE` requires at least one engagement of the matter in `ACTIVE` status (else `ERR_NO_ACTIVE_ENGAGEMENT`), an `APPROVED` budget (else `ERR_NO_APPROVED_BUDGET`), and the owning counsel. From `REOPENED`, the same call returns the matter to `ACTIVE` with a lighter staffing check — at least one engagement in `ACTIVE` or `SUSPENDED` suffices, and no `APPROVED` budget is re-required on this path — and still requires the owning counsel. Both paths recompute the posture and increment the matter's `version`.

### 3.3. Panel Governance and Outside Counsel Engagements

Outside counsel must be vetted before they can be staffed. A `LegalOperationsAnalyst` registers a firm with its `firm_name`, a `blended_rate_cap_cents` ceiling on the blended hourly rate the firm may bill (a positive number of cents per hour), and an optional `is_active` flag defaulting to true; the firm starts with `panel_status` `PENDING` and `conflict_check_status` `UNCHECKED`. Conflict screening is recorded by operations through a `result` of `CLEARED`, `WAIVED`, or `FLAGGED`, which sets `conflict_check_status` and increments the firm's `version`; screening may be recorded at any panel status. Only the `GeneralCounsel` may then approve the firm onto the panel, and only when the firm is `PENDING` with a conflict result of `CLEARED` or `WAIVED`; a firm that is not panel-`APPROVED`, or whose conflicts remain `UNCHECKED` or were `FLAGGED`, blocks the action with `ERR_REFERENCE_STATE_INVALID`. The firm list supports `panel_status` and `is_active` filters.

Panel discipline continues after approval. The `GeneralCounsel` may suspend an `APPROVED` firm, which moves it to `SUSPENDED` and cascades: every engagement referencing that firm in `ACTIVE` status moves to `SUSPENDED`, each such engagement incrementing its own `version`. Reinstating the firm moves `SUSPENDED` → `APPROVED`, but engagements suspended by the cascade do not ride back automatically — each must be reinstated individually. Termination, from `APPROVED` or `SUSPENDED`, is final and is refused with `ERR_REFERENCE_STATE_INVALID` while any engagement of the firm remains `ACTIVE` or `APPROVED`; engagements must be wound down first. A firm's engagements can be listed directly from the firm for reverse reachability.

Staffing a matter means proposing an engagement on it. The owning counsel supplies the `firm_id`, a `role_type` of `LEAD_COUNSEL`, `CO_COUNSEL`, `LOCAL_COUNSEL`, or `SPECIALIST`, and a `fee_arrangement` of `HOURLY`, `FLAT_FEE`, `CONTINGENCY`, or `HYBRID` — hourly engagements accrue via the blended rate, flat-fee via milestones, contingency via an outcome percentage. For `HOURLY` or `HYBRID` arrangements a `proposed_rate_cents` is required and must not exceed the firm's `blended_rate_cap_cents`, an overage rejected with `ERR_RATE_CAP_EXCEEDED`; for `CONTINGENCY` or `HYBRID` a `contingency_pct` between 1 and 40 inclusive is required, values outside that range rejected with `ERR_FIELD_CONSTRAINT`. When the engagement replaces prior counsel, `supersedes_engagement_id` names the engagement being superseded — an engagement of the same matter, enforced by `ERR_CROSS_REFERENCE_MISMATCH`. The proposal starts `PROPOSED` with `engagement_letter_executed` defaulting to false.

Approval belongs to the `DeputyGeneralCounsel` and checks, beyond the firm's panel and conflict state and the rate cap, that the linked matter is in `STAFFING`, `ACTIVE`, or `REOPENED`. Segregation of duties applies to lead counsel: for a `LEAD_COUNSEL` engagement the approver must not be the matter's owning counsel. Approval stamps `approved_by_user_id` for audit, increments the engagement's `version`, and performs the supersession compensation — when `supersedes_engagement_id` is set, the superseded engagement moves from `ACTIVE` or `SUSPENDED` to `TERMINATED`. A proposal may instead be rejected, `PROPOSED` → `REJECTED`, which is terminal. A `PROPOSED` engagement that is neither approved nor rejected stays inert.

Two more steps bring counsel to life. While the engagement is `PROPOSED` or `APPROVED`, the owning counsel may update `engagement_letter_executed` to record the countersigned letter; the update outside those states is rejected with `ERR_INVALID_STATE`. Activating the engagement (`APPROVED` → `ACTIVE`) then requires the letter to be executed — activation without it fails with `ERR_ENGAGEMENT_LETTER_REQUIRED` — and a linked matter in `STAFFING`, `ACTIVE`, or `REOPENED`.

Engagements cycle with the matter's fortunes. The owning counsel may suspend an `ACTIVE` engagement and later reinstate it, `SUSPENDED` → `ACTIVE`, though reinstatement is impossible while the matter sits in `SETTLEMENT_PENDING`, since settlement posture requires counsel to stand down. Termination by the `DeputyGeneralCounsel` is reachable from either `ACTIVE` or `SUSPENDED`. Engagements of a matter list with a `status` filter; the cross-matter engagement list supports `firm_id`, `matter_id`, `approved_by_user_id`, `supersedes_engagement_id`, and `status` filters for audit of who approved what and which engagements replaced which.

### 3.4. The Spend Ledger: Accruals, Posting, and Correction

Spend against a matter accumulates in an append-only ledger of accrual entries. The owning counsel creates an entry in `DRAFT` with the `engagement_id` it is reported against, a `period` in `YYYY-MM` form, an `entry_kind` of `ACCRUAL` (an estimate of unbilled fees), `INVOICE` (billed fees), or `ADJUSTMENT` (a reversal of a prior entry), and a signed `amount_cents`: `ACCRUAL` and `INVOICE` amounts must be positive, an `ADJUSTMENT` amount must be negative, and an `ADJUSTMENT` must name the entry it reverses via `reverses_entry_id`. Sign violations are rejected with `ERR_FIELD_CONSTRAINT`. Recall from §2.4 that these rows carry only `id` and `created_at` — the ledger never edits, it corrects.

Submission moves an entry `DRAFT` → `SUBMITTED` and stamps `submitted_at`. Submission is allowed while the linked matter is in `STAFFING`, `ACTIVE`, `REOPENED`, or `SETTLEMENT_PENDING`, requires the linked engagement to be `ACTIVE` or `SUSPENDED`, and is refused outright — `ERR_MATTER_POSTURE_FROZEN` — while the matter's posture is `FROZEN`. Posting belongs to `FinanceBusinessPartner`. For an `ACCRUAL` or `INVOICE`, posting is refused with `ERR_DUPLICATE` when another `POSTED` entry already exists for the same engagement, period, and entry kind: one posted entry per `engagement_id`, `period`, and `entry_kind` triple. For an `ADJUSTMENT`, the entry named by `reverses_entry_id` must itself be `POSTED`, and the adjustment's absolute amount must not exceed the reversed entry's amount.

Posting is where the ledger bites. The posted amount is added to the matter's `accrued_to_date_cents`; if the matter has an `APPROVED` budget its `utilization_pct` is recomputed; and if that recomputation pushes utilization to 90 or above, the posture ladder re-evaluates and the matter may flip `OPEN` → `RESTRICTED` on this posting — the threshold trigger that tightens the matter mid-flight. Posting an `ADJUSTMENT` additionally voids the entry it reverses: the reversed entry moves `POSTED` → `VOID` under system control and its original amount comes back out of `accrued_to_date_cents`, the compensating invariant that keeps the ledger balanced. A submitted entry may also be voided manually, `SUBMITTED` → `VOID`, which touches nothing downstream.

Formally, a matter's `accrued_to_date_cents` is the sum of `amount_cents` over its `POSTED` accrual entries — `DRAFT`, `SUBMITTED`, and `VOID` rows never count — plus the `amount_cents` of its `DISBURSED` payment requests whose disbursement rail reads `SENT` or `CONFIRMED`. A payment whose rail is `RETURNED` is excluded: returned money unwinds. This rollup recomputes on every accrual posting and void, and on every payment disbursement, return, and redisbursement. Entries of a matter list with `status`, `entry_kind`, and `period` filters; an engagement's entries can be listed from the engagement; and the cross-matter ledger list supports `matter_id`, `engagement_id`, `reverses_entry_id`, `status`, `entry_kind`, and `period` filters, which is how Finance walks a reversal chain.

### 3.5. Preservation Duties: Litigation Holds and Custodians

When preservation duties attach, the owning counsel drafts a litigation hold on the matter with a `scope_description` of the documents and data subject to preservation; the hold starts in `DRAFT`. Custodians are then added one staff user at a time by `staff_user_id` — each custodian unique per hold, duplicates rejected with `ERR_DUPLICATE` — and each new custodian row starts `NOTICED` with `noticed_at` stamped from the logical clock and `escalation_count` at zero; custodians may be added while the hold is `DRAFT`, `ISSUED`, or `ACKNOWLEDGED`, and only a `RELEASED` hold refuses new custodians with `ERR_INVALID_STATE`. Issuing the hold (`DRAFT` → `ISSUED`) requires the matter to be in `ASSESSMENT`, `STAFFING`, `ACTIVE`, or `REOPENED`, at least one custodian under the hold, and a non-`FROZEN` posture; issuance stamps `issued_at`, refreshes the `noticed_at` of every `NOTICED` custodian to the current clock (a custodian already stamped with that exact instant is left untouched), and increments the hold's `version`. One nuance matters for day-to-day work: an issued-but-unacknowledged hold does not block creating or modifying discovery or deadline data on the matter. Preservation gates release and closure, not ordinary docketing.

Acknowledgement is personal. A custodian acknowledges their own notice — acting under the `StaffUser` role with an `X-User-ID` equal to the custodian row's `staff_user_id`, failing which the call is rejected with `ERR_CUSTODIAN_SELF_ACK_REQUIRED` — from either `NOTICED` or `ESCALATED`, provided the parent hold is still in `DRAFT` or `ISSUED`. Acknowledgement stamps `acknowledged_at` and bubbles up: when the acknowledgement leaves zero custodians in `NOTICED` or `ESCALATED` and at least one custodian stands `ACKNOWLEDGED`, the parent hold auto-transitions `ISSUED` → `ACKNOWLEDGED`. A hold whose custodians are all `EXEMPTED` never auto-acknowledges; someone must actually acknowledge.

Counsel has two tools for the unresponsive. Escalation moves a `NOTICED` custodian to `ESCALATED` and increments `escalation_count`, but only while the parent hold is `ISSUED` and only once at least five full days have elapsed since `noticed_at` on the logical clock — an early escalation is rejected with `ERR_SCHEDULE_CONFLICT`. Exemption moves a custodian from `NOTICED` or `ESCALATED` to `EXEMPTED` and requires an `exemption_reason`; it runs the same bubble-up check, so exempting the last pending custodian can auto-acknowledge the hold if at least one other custodian has acknowledged. Custodian rows list per hold with a `status` filter, and a staff member's custodianships across all holds are listed from their staff record.

Release closes the preservation duty. Counsel releases a hold from `ISSUED`, `ACKNOWLEDGED`, or `DRAFT` by supplying a `release_reason` of `MATTER_RESOLVED`, `SCOPE_NARROWED`, `COURT_ORDER`, or `ERROR`; release stamps `released_at` and, when the hold was `ISSUED` or `ACKNOWLEDGED`, cascades every custodian in `NOTICED`, `ACKNOWLEDGED`, or `ESCALATED` to `RELEASED` — releasing a `DRAFT` hold leaves its custodians' statuses untouched. The pin rule guards the pin: while any work order referencing the hold is `AUTHORIZED` or `IN_PROGRESS`, release is rejected with `ERR_HOLD_COMPLIANCE_BLOCK` — active collection work pins the hold open. Holds of a matter list with a `status` filter.

### 3.6. Discovery Vendors and Work Orders

E-discovery capacity is a managed resource. A `LegalOperationsAnalyst` registers each vendor with a `vendor_name`, a `security_clearance_level` of `STANDARD`, `ENHANCED`, or `RESTRICTED`, a total monthly `capacity_gb` greater than zero, and an optional `is_active` flag defaulting to true; inactive vendors cannot receive new work orders. The vendor's `committed_gb` is derived: the sum of `estimated_gb` over that vendor's work orders in `AUTHORIZED` or `IN_PROGRESS` — `DRAFT`, `COMPLETED`, and `CANCELLED` orders hold no capacity — recomputed whenever an order is authorized, completed, or cancelled. Vendor lists filter by `security_clearance_level` and `is_active`.

A work order is drafted on a matter by operations, naming the `vendor_id`, the `hold_id` whose custodians' data is being collected, a `service_type` of `COLLECTION`, `PROCESSING`, `HOSTING`, `REVIEW`, or `PRODUCTION`, an `estimated_gb` volume greater than zero, a negotiated `rate_per_gb_cents` greater than zero, and a `scheduled_start` and `scheduled_end` with the end strictly after the start (`ERR_FIELD_CONSTRAINT` otherwise). The referenced hold must belong to the same matter and be in `ISSUED` or `ACKNOWLEDGED`, enforced by `ERR_CROSS_REFERENCE_MISMATCH`. At creation the server computes the provisional `estimated_cost_cents` using marginal per-tier pricing: the first 100 GB bill at the full negotiated rate; the next 400 GB — gigabytes 101 through 500 — bill at 80 percent of that rate; any volume beyond 500 GB bills at 60 percent. Floor division is applied to each tier's subtotal before the subtotals are summed, and this pinned rounding order is part of the contract.

Authorization (`DRAFT` → `AUTHORIZED`) is the most heavily gated action in the system, and the gates have a fixed story. The matter must be `ACTIVE` or `REOPENED`; its posture must be `OPEN`, since `RESTRICTED` or `FROZEN` blocks new spend authorization with `ERR_MATTER_POSTURE_FROZEN`; the hold must be `ISSUED` or `ACKNOWLEDGED`; the vendor must be active. Then the clearance matrix: a `CLASS_ACTION` or `REGULATORY` matter accepts only a `RESTRICTED`-clearance vendor; an `EMPLOYMENT` or `IP` matter requires `ENHANCED` or `RESTRICTED`; `COMMERCIAL` and `PRODUCT_LIABILITY` accept any clearance — an insufficient clearance is `ERR_VENDOR_CLEARANCE_INSUFFICIENT`. Then capacity: `committed_gb` plus the order's `estimated_gb` must not exceed the vendor's `capacity_gb`, else `ERR_VENDOR_CAPACITY_EXCEEDED`. Finally the temporal gate: no other work order of the same vendor in `AUTHORIZED` or `IN_PROGRESS` may have a window overlapping this order's — windows are half-open, so an order ending exactly when another begins is adjacency, not conflict — and a clash is `ERR_SCHEDULE_CONFLICT`. Authorization debits capacity (`committed_gb` grows by `estimated_gb`), recomputes the estimated cost, and increments the order's `version`.

Starting an authorized order (`AUTHORIZED` → `IN_PROGRESS`) may not happen before its `scheduled_start` on the logical clock — early starts fail with `ERR_SCHEDULE_CONFLICT` — and is blocked while the matter's posture is `FROZEN`. Completion (`IN_PROGRESS` → `COMPLETED`) takes the `actual_gb` processed, which must be zero or greater, releases the estimated capacity back to the vendor, and recomputes the final cost: when `actual_gb` is greater than zero the tiered calculation runs on the actual volume; when it is exactly zero the provisional estimate stands, there being no cost basis. Completion never synthesizes an accrual entry — vendor cost reaches the ledger only through invoices. Cancellation is reachable from `DRAFT`, `AUTHORIZED`, or `IN_PROGRESS`; cancelling an authorized or in-progress order releases its capacity debit. Work orders list per matter with a `status` filter, and reverse lists expose a vendor's orders (with `status` filter) and the orders pinning a given hold.

### 3.7. The Court Calendar: Deadline Outcomes and Jurisdictional Freezes

Once seeded, calendar entries live under the logical clock. Marking a deadline met (`SCHEDULED` → `MET`) stamps `completed_at` and is only possible while the clock has not passed `due_at`; after the moment has passed the honest record is a miss, and a late mark-met is rejected with `ERR_DEADLINE_TIMING`. A miss is recorded in two ways: counsel may declare it manually at any time from `SCHEDULED` — a declaration of intent that the date will not be made — or the clock sweep fires `SCHEDULED` → `MISSED` automatically once the clock moves past `due_at`. Either way, when the missed deadline has `is_jurisdictional` true, the matter's posture flips to `FROZEN` per the ladder in §2.9 and stays frozen until the deadline is vacated with a court-order note.

Vacating moves a deadline from `SCHEDULED` or `MISSED` to `VACATED` and is shared between the owning counsel and the `DeputyGeneralCounsel`. For a jurisdictional deadline the caller must supply a non-empty `court_order_reference`; without it the vacate is rejected with `ERR_INVALID_REQUEST`. For a non-jurisdictional deadline the reference is optional but, when supplied, must still be a non-empty string; the reference is not stored on the deadline either way. Vacating the deadline whose miss froze the matter re-runs the posture ladder and may unfreeze it. When the matter itself resolves, the resolution cascade vacates every still-`SCHEDULED` deadline without any court-order reference — the system's own cascade bypasses that requirement. Finally, a deadline that sits `MISSED` until the logical clock passes thirty days beyond its `due_at` is swept to `EXPIRED` by the clock. The calendar list for a matter sorts by `due_at` ascending — the exception to the default creation-order sort — and filters by `status` and `deadline_type`.

### 3.8. Settlement Authority, Negotiation, and Payment

#### Authority Policy and the Approval Ladder

Who may approve a settlement depends on how large the matter looked when the request was submitted. The `GeneralCounsel` maintains the policy table: each row names a `tier` (`TIER_1` through `TIER_4`, unique among active rows — a second active row for the same tier is `ERR_DUPLICATE`), the `approver_role` whose sign-off that tier requires (one of `DeputyGeneralCounsel`, `GeneralCounsel`, `ChiefFinancialOfficer`, `BoardCommittee`), a positive `max_single_amount_cents` ceiling that role may approve alone, and a `dual_approval_required_over_cents` threshold at or above the single-approval ceiling over which a second approver is also required. Only active rows (`is_active`, default true) are consulted, and the policy list filters by `tier` and `is_active`.

The approval hierarchy is a strict ladder: `LitigationCounsel` ranks below `DeputyGeneralCounsel`, which ranks below `GeneralCounsel`, then `ChiefFinancialOfficer`, then `BoardCommittee`. A request at or below the policy's single-approval ceiling needs exactly one approval, from the role the policy names; an amount exactly equal to the ceiling still needs only one. One cent over the ceiling requires two approvals: the first from the policy-named role, the second from a role ranked strictly above the first approver's — and only when `dual_approval_required_over_cents` reaches the proposed amount; an amount above even the dual threshold cannot be approved at all and is rejected with `ERR_SETTLEMENT_AUTHORITY`. An approval from the wrong role for the snapshot tier, or one that skips the dual path, is likewise `ERR_SETTLEMENT_AUTHORITY`. Approvals are evaluated in the order the successful approve calls arrive, and the segregation-of-duties check of §2.8 runs first: the requester and any prior approver are turned away with `ERR_SEGREGATION_OF_DUTIES`.

#### The Negotiation Cycle

The owning counsel drafts a settlement request on a matter with a `proposed_amount_cents` greater than zero, a `settlement_kind` of `PAY_OUT` (the company pays), `PAY_IN` (the company receives), or `NON_MONETARY`, a free-text `terms_summary`, and an `expires_at` offer expiry; the create is version-guarded per §2.7, so the body carries `expected_matter_version`, and a successful create increments the matter's `version`. Submission (`DRAFT` → `SUBMITTED`) requires the matter in `ACTIVE` or `REOPENED`, a non-`FROZEN` posture, and the owning counsel personally; a `NON_MONETARY` settlement carries a nominal one-cent amount — `proposed_amount_cents` of exactly 1 — and any other amount on a non-monetary request is rejected with `ERR_FIELD_CONSTRAINT`. Submission stamps `requested_by_user_id` and, crucially, snapshots `authority_tier_at_submission` from the matter's current `exposure_tier`: approval routing consults this snapshot, not the live tier, so mid-negotiation re-tiering never moves the goalposts on a request already in flight.

A `DeputyGeneralCounsel` begins review (`SUBMITTED` → `UNDER_REVIEW`). Approval then accumulates as described above: each successful approve appends the acting user's id to `approved_by_user_ids` and increments the request's `version`. For a dual-approval amount the first approval leaves the request in `UNDER_REVIEW` — a self-loop at the API level — and only the second, higher-ranked approval completes it. When the required count is reached the request becomes `APPROVED` and the linked matter auto-transitions from `ACTIVE` or `REOPENED` to `SETTLEMENT_PENDING`, suspending every `ACTIVE` engagement of the matter to `SUSPENDED` (each engagement's `version` increments) and recomputing posture and matter `version`.

Negotiation is a first-class cycle. A `DeputyGeneralCounsel` counters a request under review (`UNDER_REVIEW` → `COUNTERED`) with a `counter_amount_cents` that must be positive and different from the current ask, failing which the counter is rejected with `ERR_FIELD_CONSTRAINT`; countering sets `counter_amount_cents` and clears `approved_by_user_ids` back to empty — a new negotiation round resets prior partial approvals. The requesting counsel, and only the requesting counsel, accepts the counter (`COUNTERED` → `UNDER_REVIEW`): the counter amount replaces `proposed_amount_cents` as the ask and the authority tier is re-snapshotted from the matter's current `exposure_tier`, re-pinning routing to the new amount. The cycle `UNDER_REVIEW` → `COUNTERED` → `UNDER_REVIEW` may repeat any number of times. The `GeneralCounsel` may reject from `UNDER_REVIEW` or `COUNTERED` (`REJECTED` is terminal), and the owning counsel may withdraw the request to `WITHDRAWN` from `DRAFT`, `SUBMITTED`, `UNDER_REVIEW`, or `COUNTERED` — from the three post-submission states only the recorded `requested_by_user_id` may withdraw, while a `DRAFT` request has no requester yet and may be withdrawn freely. Both rejection and withdrawal clear any recorded counter amount. Should the logical clock pass `expires_at` while the request sits in `SUBMITTED`, `UNDER_REVIEW`, or `COUNTERED`, the system sweeps it to `EXPIRED` and clears any recorded approvals.

Execution is deliberately staged. The `GeneralCounsel` executes an `APPROVED` request only when the linked matter stands in `SETTLEMENT_PENDING` and a payment request for this settlement already exists in `FINANCE_APPROVED` — the money must be staged before the deal is done, and executing without it is rejected with `ERR_REFERENCE_STATE_INVALID`. Execution moves the request to `EXECUTED` and drives the matter from `SETTLEMENT_PENDING` to `RESOLVED` with `resolution_type` `SETTLEMENT` and the full resolution cascade of §3.9. Settlement requests list per matter with a `status` filter, and the cross-matter list filters by `matter_id`, `requested_by_user_id`, and `status`.

#### Paying Out: Payment Requests and the Disbursement Rail

Payment requests carry two independent state dimensions. The approval lifecycle runs `DRAFT` → `SUBMITTED` → `FINANCE_APPROVED` → `DISBURSED`, with `REJECTED` and `CANCELLED` as terminal exits; the disbursement rail, `payment_status`, runs `NOT_SENT` → `SENT` → `CONFIRMED`, with a `SENT` → `RETURNED` → `SENT` recovery loop. The rail moves partly under system control and partly under Finance, and rail actions from the wrong rail state are rejected with `ERR_PAYMENT_RAIL_STATE`.

The owning counsel drafts a payment with a `payment_kind` — `SETTLEMENT` pays an executed-to-be settlement, `JUDGMENT` pays an adverse judgment, `COST_AWARD` pays statutory costs — an `amount_cents` greater than zero, and a `payee_name`; for `SETTLEMENT` payments a `settlement_request_id` is required and must reference a settlement of the same matter (`ERR_CROSS_REFERENCE_MISMATCH`). Submission gates on the matter being in `SETTLEMENT_PENDING`, `RESOLVED`, `ACTIVE`, or `REOPENED`, and on the kind: a `SETTLEMENT` payment requires the linked settlement request to be `APPROVED` (else `ERR_REFERENCE_STATE_INVALID`) and its amount must equal the settlement's `proposed_amount_cents` exactly (else `ERR_FIELD_CONSTRAINT`); a `JUDGMENT` payment requires the matter to be `RESOLVED` with `resolution_type` `JUDGMENT`. Submission stamps `submitted_by_user_id`.

Finance approval enforces §2.8 — the approver must not be the submitter — and then the fiscal gate: the matter must have an `APPROVED` budget (absent one, the rejection is `ERR_NO_APPROVED_BUDGET`), and the payment amount must fit within the fiscal-year headroom, that is `fy_budget_cents` minus the matter's `accrued_to_date_cents`; an overage is `ERR_BUDGET_EXCEEDED`. Approval stamps `approved_by_user_id`. Disbursement requires the rail to still read `NOT_SENT`; it stamps `disbursed_at`, moves the rail to `SENT`, adds the amount to the matter's `accrued_to_date_cents` — payments count as accrued spend — and recomputes the reserve to burn it down. Disbursing a settlement payment does not execute the settlement; the settlement waits for the explicit execution step above. Finance then confirms receipt (`SENT` → `CONFIRMED`) or marks the payment returned (`SENT` → `RETURNED`), the latter subtracting the amount back out of the matter's accrued spend and recomputing the reserve; a returned payment can be redisbursed (`RETURNED` → `SENT`) while the request remains `DISBURSED`, re-accruing the amount. This unwind-and-re-accrue pair is the compensating invariant that keeps the ledger exact across returned funds. Finance may also reject a `SUBMITTED` request, and the submitter may cancel from `DRAFT` or `SUBMITTED` — a draft, having no submitter, may be cancelled freely. Payment requests list per matter with `status` and `payment_kind` filters, per settlement for reverse reachability, and across matters with `matter_id`, `settlement_request_id`, `submitted_by_user_id`, `approved_by_user_id`, `status`, and `payment_kind` filters.

### 3.9. Resolution, Reopening, Closure, and Portfolio Oversight

A matter resolves by one of two doors, and the doors differ in their side effects. The settlement door was described in §3.8: when an approved settlement is executed, the matter auto-transitions `SETTLEMENT_PENDING` → `RESOLVED`, its `resolution_type` is set to `SETTLEMENT`, and — because the matter passed through `SETTLEMENT_PENDING` — its engagements were already suspended at approval time. The courtroom door is a direct resolve by the owning counsel from `ACTIVE` or `REOPENED`, naming a `resolution_type` of `JUDGMENT`, `DISMISSAL`, or `SUMMARY_JUDGMENT` — a `SETTLEMENT` resolution flows only through the settlement pipeline and is never accepted on the direct call. Direct resolution is refused with `ERR_OPEN_LIMITATION_EXPOSURE` while any `LIMITATION_EXPIRY` deadline of the matter is still `SCHEDULED`: open limitation exposure must be vacated first. It is also owner-gated (`ERR_NOT_MATTER_OWNER`), and unlike the settlement door it does not suspend engagements — the branching side-effect sets differ deliberately between the two paths.

Whichever door is taken, resolution stamps `resolved_at` and runs the same cascade in a pinned order. First, every work order of the matter in `DRAFT`, `AUTHORIZED`, or `IN_PROGRESS` moves to `CANCELLED`, each releasing its vendor-capacity debit and — by cancelling the orders that pinned them — unpinning the holds. Second, every litigation hold in `DRAFT`, `ISSUED`, or `ACKNOWLEDGED` moves to `RELEASED` with `release_reason` `MATTER_RESOLVED`; because the work orders cancelled first, the release-time pin check is vacuous during this system-driven flow. Third, every custodian under those holds in `NOTICED`, `ACKNOWLEDGED`, or `ESCALATED` moves to `RELEASED`. Fourth — on the direct-resolve path — every still-`SCHEDULED` deadline moves to `VACATED`. The reserve then recomputes under its post-resolution variant: the reserve becomes the excess, floored at zero, of staged-but-undisbursed payments over the matter's `accrued_to_date_cents` (posted accruals plus disbursed, unreturned payments, per §3.4), where staged payments are the matter's payment requests in `FINANCE_APPROVED` — a resolved matter carries reserve only for money already staged. The posture recomputes (a resolved matter is `FROZEN` per the ladder) and the matter's `version` increments.

Resolution is not necessarily the end. A `DeputyGeneralCounsel` may reopen a `RESOLVED` matter by supplying a non-empty `reopen_reason` (missing or empty, the call is `ERR_INVALID_REQUEST`) — but only while no payment request of the matter stands `DISBURSED` with its rail `CONFIRMED`; money confirmed in the recipient's hands makes reopening impossible and yields `ERR_REOPEN_BLOCKED_BY_CONFIRMED_PAYMENT`. Reopening clears `resolved_at` to null while retaining `resolution_type` for audit, restores the reserve to its full probability-scaled value under the reopened variant — the accrued subtraction is skipped, historical spend being treated as sunk — and lands the matter in `REOPENED`, which carries `ASSESSMENT`-equivalent privileges (budgets may be submitted, holds issued, engagements approved against it) while remaining distinguishable from a fresh `ASSESSMENT` matter for reporting. From `REOPENED` the matter activates per §3.2 and may resolve again: the cycle `RESOLVED` → `REOPENED` → `RESOLVED` is fully supported.

Closure is the terminal act and belongs to the `LegalOperationsAnalyst`. From `RESOLVED`, closure requires that every hold of the matter is `RELEASED`, every work order is `COMPLETED` or `CANCELLED`, and every payment request is `DISBURSED`, `REJECTED`, or `CANCELLED`; the request body must carry `close_checklist_ack` set to true — the flag defaults to false on the matter, and a missing or false value is rejected with `ERR_INVALID_REQUEST` — acknowledging that holds are released and vendors demobilized. Unreleased holds, non-terminal work orders, or non-terminal payments block the close with `ERR_HOLD_COMPLIANCE_BLOCK`. An early-exit branch covers mistaken intake: a matter still in `INTAKE` may be closed directly when no engagement, hold, work order, settlement request, or payment request exists for it — the presence of any such child record blocks the close with `ERR_HOLD_COMPLIANCE_BLOCK` — again with `close_checklist_ack` true. `CLOSED` is terminal in both directions.

Two read models serve oversight. The matter summary returns the matter's `reserve_amount_cents` and `accrued_to_date_cents` as they stand on the matter row; `utilization_pct` mirroring the `APPROVED` budget (zero when none exists); `open_deadline_count`, the count of its deadlines still `SCHEDULED`; `active_hold_count`, the count of its holds in `DRAFT`, `ISSUED`, or `ACKNOWLEDGED`; and `committed_vendor_estimate_cents`, the sum of `estimated_cost_cents` over its work orders in `AUTHORIZED` or `IN_PROGRESS`. The portfolio report groups matters into cohorts by `exposure_tier`, honoring optional `matter_type` and `exposure_tier` query filters; the `cohorts` array always contains all four tiers in ascending order `TIER_1` through `TIER_4`, and for each cohort reports `resolved_count` — matters in `RESOLVED` or `CLOSED`, the two counting together — `total_accrued_cents`, the sum of accrued spend across the cohort; `avg_exposure_cents`, the floor of the mean of each matter's low-plus-high midpoint; and `outcome_favorability_pct`, the floored percentage of resolved matters whose `resolution_type` is `DISMISSAL` or `SUMMARY_JUDGMENT`, which reads zero for a cohort with no resolutions. Alongside the `cohorts` array the report carries `open_exposure_cents` — the sum of `exposure_high_cents` over every filtered matter in `STAFFING`, `ACTIVE`, `REOPENED`, or `SETTLEMENT_PENDING` — and `total_matters`, the count of matters surviving the filters. Empty cohorts report zeros, never nulls. Matters without a computed `exposure_tier` belong to no cohort but still count toward `total_matters`.

## 4. Endpoint Definitions

Operations that create a new resource — a matter, a budget, an engagement, an accrual entry, a hold, a custodian, a work order, a deadline, a policy row, a settlement request, a payment request, a staff user, a firm, or a vendor — return `201 Created`. Operations that modify an existing resource or drive a state transition, and all reads, return `200 OK`. The table below is a summary only; the request payloads, derived fields, and side effects are specified by the narratives of §2 and §3, not here. In the Authorized Role(s) column, "Read set" denotes `LitigationCounsel`, `DeputyGeneralCounsel`, `GeneralCounsel`, `LegalOperationsAnalyst`, and `FinanceBusinessPartner`; "Read set + CFO" additionally includes `ChiefFinancialOfficer`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/litigation/_clock/set_current_utc` | Set the logical clock and run the time-driven sweeps | LegalOperationsAnalyst |
| POST | `/litigation/staff-users` | Create a staff user | LegalOperationsAnalyst |
| GET | `/litigation/staff-users` | List staff users | Read set + CFO |
| GET | `/litigation/staff-users/{id}` | Fetch one staff user | Read set + CFO |
| POST | `/litigation/counsel-firms` | Register an outside counsel firm (panel PENDING, conflicts UNCHECKED) | LegalOperationsAnalyst |
| GET | `/litigation/counsel-firms` | List counsel firms | Read set |
| GET | `/litigation/counsel-firms/{id}` | Fetch one firm | Read set |
| POST | `/litigation/counsel-firms/{id}/conflict-check` | Record the conflict screening result | LegalOperationsAnalyst |
| POST | `/litigation/counsel-firms/{id}/approve-panel` | Approve a firm onto the panel | GeneralCounsel |
| POST | `/litigation/counsel-firms/{id}/suspend` | Suspend a panel firm, cascading engagement suspension | GeneralCounsel |
| POST | `/litigation/counsel-firms/{id}/reinstate` | Reinstate a suspended firm | GeneralCounsel |
| POST | `/litigation/counsel-firms/{id}/terminate` | Terminate a firm with no ACTIVE/APPROVED engagements | GeneralCounsel |
| GET | `/litigation/counsel-firms/{id}/engagements` | List engagements of a firm | Read set |
| POST | `/litigation/matters` | Intake a new matter | LitigationCounsel |
| GET | `/litigation/matters` | List matters | Read set + CFO |
| GET | `/litigation/matters/{id}` | Fetch one matter including computed fields | Read set + CFO |
| PATCH | `/litigation/matters/{id}` | Update intake and exposure fields (INTAKE/ASSESSMENT only) | LitigationCounsel |
| POST | `/litigation/matters/{id}/submit-assessment` | Move INTAKE to ASSESSMENT | LitigationCounsel |
| POST | `/litigation/matters/{id}/advance-to-staffing` | Move ASSESSMENT to STAFFING | LitigationCounsel |
| POST | `/litigation/matters/{id}/activate` | Move STAFFING or REOPENED to ACTIVE | LitigationCounsel |
| POST | `/litigation/matters/{id}/resolve` | Resolve the matter with the full cascade | LitigationCounsel |
| POST | `/litigation/matters/{id}/reopen` | Reopen a resolved matter | DeputyGeneralCounsel |
| POST | `/litigation/matters/{id}/close` | Close the matter (checklist-gated) | LegalOperationsAnalyst |
| POST | `/litigation/matters/{id}/engagements` | Propose an engagement on the matter | LitigationCounsel |
| GET | `/litigation/matters/{id}/engagements` | List engagements of a matter | Read set |
| GET | `/litigation/engagements/{id}` | Fetch one engagement | Read set |
| PATCH | `/litigation/engagements/{id}` | Record engagement letter execution (PROPOSED/APPROVED only) | LitigationCounsel |
| POST | `/litigation/engagements/{id}/approve` | Approve a proposed engagement (SoD-gated) | DeputyGeneralCounsel |
| POST | `/litigation/engagements/{id}/reject` | Reject a proposed engagement | DeputyGeneralCounsel |
| POST | `/litigation/engagements/{id}/activate` | Activate an approved engagement (requires executed letter) | LitigationCounsel |
| POST | `/litigation/engagements/{id}/suspend` | Suspend an active engagement | LitigationCounsel |
| POST | `/litigation/engagements/{id}/reinstate` | Reinstate a suspended engagement | LitigationCounsel |
| POST | `/litigation/engagements/{id}/terminate` | Terminate an ACTIVE or SUSPENDED engagement | DeputyGeneralCounsel |
| POST | `/litigation/matters/{id}/budgets` | Create a budget (version-guarded on the matter) | LitigationCounsel |
| GET | `/litigation/matters/{id}/budgets` | List budgets of a matter | Read set |
| GET | `/litigation/budgets/{id}` | Fetch one budget | Read set |
| POST | `/litigation/budgets/{id}/submit` | Submit a draft budget | LitigationCounsel |
| POST | `/litigation/budgets/{id}/approve` | Approve a submitted budget (SoD and fiscal gates; supersedes prior) | FinanceBusinessPartner |
| POST | `/litigation/budgets/{id}/reject` | Reject a submitted budget | FinanceBusinessPartner |
| POST | `/litigation/matters/{id}/accrual-entries` | Create an accrual, invoice, or adjustment entry | LitigationCounsel |
| GET | `/litigation/matters/{id}/accrual-entries` | List accrual entries of a matter | Read set |
| GET | `/litigation/engagements/{id}/accrual-entries` | List accrual entries of an engagement | Read set |
| GET | `/litigation/accrual-entries/{id}` | Fetch one accrual entry | Read set |
| POST | `/litigation/accrual-entries/{id}/submit` | Submit an accrual entry | LitigationCounsel |
| POST | `/litigation/accrual-entries/{id}/post` | Post a submitted entry, syncing the ledger | FinanceBusinessPartner |
| POST | `/litigation/accrual-entries/{id}/void` | Void a submitted entry | FinanceBusinessPartner |
| POST | `/litigation/matters/{id}/holds` | Create a litigation hold | LitigationCounsel |
| GET | `/litigation/matters/{id}/holds` | List holds of a matter | Read set |
| GET | `/litigation/holds/{id}` | Fetch one hold | Read set |
| POST | `/litigation/holds/{id}/issue` | Issue a hold | LitigationCounsel |
| POST | `/litigation/holds/{id}/release` | Release a hold (blocked by pinning work orders) | LitigationCounsel |
| POST | `/litigation/holds/{id}/custodians` | Add a custodian to a hold | LitigationCounsel |
| GET | `/litigation/holds/{id}/custodians` | List custodians of a hold | Read set |
| GET | `/litigation/staff-users/{id}/custodianships` | List a staff user's custodianships | LitigationCounsel, DeputyGeneralCounsel, GeneralCounsel, LegalOperationsAnalyst |
| GET | `/litigation/hold-custodians/{id}` | Fetch one custodian row | Read set |
| POST | `/litigation/hold-custodians/{id}/acknowledge` | Custodian self-acknowledgement | StaffUser |
| POST | `/litigation/hold-custodians/{id}/escalate` | Escalate an unacknowledged custodian (five-day cooling period) | LitigationCounsel |
| POST | `/litigation/hold-custodians/{id}/exempt` | Exempt a custodian | LitigationCounsel |
| POST | `/litigation/discovery-vendors` | Register a discovery vendor | LegalOperationsAnalyst |
| GET | `/litigation/discovery-vendors` | List vendors | Read set |
| GET | `/litigation/discovery-vendors/{id}` | Fetch one vendor including committed capacity | Read set |
| POST | `/litigation/matters/{id}/work-orders` | Create a vendor work order | LegalOperationsAnalyst |
| GET | `/litigation/matters/{id}/work-orders` | List work orders of a matter | Read set |
| GET | `/litigation/discovery-vendors/{id}/work-orders` | List work orders of a vendor | Read set |
| GET | `/litigation/holds/{id}/work-orders` | List work orders pinned to a hold | Read set |
| GET | `/litigation/work-orders/{id}` | Fetch one work order | Read set |
| POST | `/litigation/work-orders/{id}/authorize` | Authorize a work order (posture, clearance, capacity, temporal gates) | LegalOperationsAnalyst |
| POST | `/litigation/work-orders/{id}/start` | Start an authorized work order (not before its window) | LegalOperationsAnalyst |
| POST | `/litigation/work-orders/{id}/complete` | Complete a work order with the actual volume | LegalOperationsAnalyst |
| POST | `/litigation/work-orders/{id}/cancel` | Cancel a work order with capacity release | LegalOperationsAnalyst |
| POST | `/litigation/matters/{id}/deadlines` | Create a deadline or hearing entry | LitigationCounsel |
| GET | `/litigation/matters/{id}/deadlines` | List deadlines of a matter, due date ascending | Read set |
| GET | `/litigation/deadlines/{id}` | Fetch one deadline | Read set |
| POST | `/litigation/deadlines/{id}/mark-met` | Mark a deadline met (only while the clock is at or before its due instant) | LitigationCounsel |
| POST | `/litigation/deadlines/{id}/mark-missed` | Declare a deadline missed | LitigationCounsel |
| POST | `/litigation/deadlines/{id}/vacate` | Vacate a deadline (jurisdictional requires a court order reference) | LitigationCounsel, DeputyGeneralCounsel |
| POST | `/litigation/settlement-authority-policies` | Create an authority policy row for a tier | GeneralCounsel |
| GET | `/litigation/settlement-authority-policies` | List authority policy rows | Read set + CFO |
| GET | `/litigation/settlement-authority-policies/{id}` | Fetch one policy row | Read set + CFO |
| POST | `/litigation/matters/{id}/settlement-requests` | Create a settlement request (version-guarded on the matter) | LitigationCounsel |
| GET | `/litigation/matters/{id}/settlement-requests` | List settlement requests of a matter | Read set + CFO |
| GET | `/litigation/settlement-requests/{id}` | Fetch one settlement request | Read set + CFO |
| POST | `/litigation/settlement-requests/{id}/submit` | Submit a settlement request, snapshotting the authority tier | LitigationCounsel |
| POST | `/litigation/settlement-requests/{id}/begin-review` | Begin review of a submitted request | DeputyGeneralCounsel |
| POST | `/litigation/settlement-requests/{id}/approve` | Approve under authority routing (single, or first-of-two for dual) | DeputyGeneralCounsel, GeneralCounsel, ChiefFinancialOfficer, BoardCommittee |
| POST | `/litigation/settlement-requests/{id}/counter` | Counter a request under review, resetting prior approvals | DeputyGeneralCounsel |
| POST | `/litigation/settlement-requests/{id}/accept-counter` | Accept the counter amount as the new ask | LitigationCounsel |
| POST | `/litigation/settlement-requests/{id}/reject` | Reject a settlement request | GeneralCounsel |
| POST | `/litigation/settlement-requests/{id}/execute` | Execute an approved settlement, resolving the matter | GeneralCounsel |
| POST | `/litigation/settlement-requests/{id}/withdraw` | Withdraw a settlement request | LitigationCounsel |
| POST | `/litigation/matters/{id}/payment-requests` | Create a payment request | LitigationCounsel |
| GET | `/litigation/matters/{id}/payment-requests` | List payment requests of a matter | Read set + CFO |
| GET | `/litigation/settlement-requests/{id}/payment-requests` | List payment requests tied to a settlement | Read set + CFO |
| GET | `/litigation/payment-requests/{id}` | Fetch one payment request (both state dimensions) | Read set + CFO |
| POST | `/litigation/payment-requests/{id}/submit` | Submit a payment request | LitigationCounsel |
| POST | `/litigation/payment-requests/{id}/finance-approve` | Finance-approve a payment (SoD and fiscal gates) | FinanceBusinessPartner |
| POST | `/litigation/payment-requests/{id}/disburse` | Disburse an approved payment, sending the rail | FinanceBusinessPartner |
| POST | `/litigation/payment-requests/{id}/confirm-receipt` | Confirm receipt of a sent payment | FinanceBusinessPartner |
| POST | `/litigation/payment-requests/{id}/mark-returned` | Mark a sent payment returned, unwinding accrued spend | FinanceBusinessPartner |
| POST | `/litigation/payment-requests/{id}/redisburse` | Redisburse a returned payment, re-accruing spend | FinanceBusinessPartner |
| POST | `/litigation/payment-requests/{id}/reject` | Reject a payment request | FinanceBusinessPartner |
| POST | `/litigation/payment-requests/{id}/cancel` | Cancel a payment request | LitigationCounsel |
| GET | `/litigation/reports/portfolio` | Portfolio outcome analytics by exposure-tier cohort | GeneralCounsel, DeputyGeneralCounsel, ChiefFinancialOfficer, FinanceBusinessPartner |
| GET | `/litigation/matters/{id}/summary` | Computed summary of one matter | Read set + CFO |
| GET | `/litigation/engagements` | Cross-matter engagement list with audit filters | Read set |
| GET | `/litigation/budgets` | Cross-matter budget list with audit and supersession filters | Read set |
| GET | `/litigation/accrual-entries` | Cross-matter accrual list with reversal-chain filter | Read set |
| GET | `/litigation/settlement-requests` | Cross-matter settlement request list | Read set + CFO |
| GET | `/litigation/payment-requests` | Cross-matter payment request list | Read set + CFO |

## 5. Error Code Catalogue

The catalogue below is a key only; the conditions under which each error is raised are specified by the narratives of §2 and §3.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_REFERENCE_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_NOT_MATTER_OWNER` | 403 Forbidden |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_HOLD_COMPLIANCE_BLOCK` | 409 Conflict |
| `ERR_MATTER_POSTURE_FROZEN` | 409 Conflict |
| `ERR_VENDOR_CLEARANCE_INSUFFICIENT` | 422 Unprocessable Entity |
| `ERR_FIELD_CONSTRAINT` | 422 Unprocessable Entity |
| `ERR_DUPLICATE` | 409 Conflict |
| `ERR_SCHEDULE_CONFLICT` | 409 Conflict |
| `ERR_DEADLINE_TIMING` | 409 Conflict |
| `ERR_CROSS_REFERENCE_MISMATCH` | 422 Unprocessable Entity |
| `ERR_REFERENCE_STATE_INVALID` | 409 Conflict |
| `ERR_RATE_CAP_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_VENDOR_CAPACITY_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_SETTLEMENT_AUTHORITY` | 403 Forbidden |
| `ERR_BUDGET_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_NO_APPROVED_BUDGET` | 409 Conflict |
| `ERR_STALE_MATTER_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_ENGAGEMENT_LETTER_REQUIRED` | 409 Conflict |
| `ERR_NO_ACTIVE_ENGAGEMENT` | 409 Conflict |
| `ERR_OPEN_LIMITATION_EXPOSURE` | 409 Conflict |
| `ERR_CUSTODIAN_SELF_ACK_REQUIRED` | 403 Forbidden |
| `ERR_REOPEN_BLOCKED_BY_CONFIRMED_PAYMENT` | 409 Conflict |
| `ERR_PAYMENT_RAIL_STATE` | 409 Conflict |
