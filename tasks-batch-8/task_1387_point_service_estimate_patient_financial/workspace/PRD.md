# Patient Financial Clearance API — Product Requirements Document

## 1. Introduction

Hospitals lose revenue and patient goodwill at the front end of the revenue cycle: a scheduled procedure arrives without a verified eligibility check, without a contracted-rate estimate the patient has accepted, without the required prior authorization, and without any deposit or financing arrangement in place. The Patient Financial Clearance API is the backend for a hospital financial clearance unit that closes that gap. It lets registration staff capture eligibility verifications, lets financial counselors build and present point-of-service estimates — contracted-rate pricing with deductible, coinsurance, and out-of-pocket accumulators for insured patients, or a federally-styled good-faith estimate for the uninsured — and lets supervisors grant or withhold financial clearance before the date of service.

Beyond the estimate itself, the system manages the money and the exceptions that surround it: prepayment deposits with a business-day refund schedule, multi-installment payment plans with default and cure handling, prior-authorization workflows with medical-necessity determinations and segregation of duties, and escalation queues for high-dollar cases and good-faith disputes. After the service is rendered, finalization compares the actual billed patient amount against what the patient was first shown and what the patient accepted, producing a variance record that feeds the unit's accuracy tracking. All time-driven behavior — snapshot staleness, authorization expiry, estimate expiry, plan default — is driven by a controllable logical clock so that the unit's operations are deterministic and auditable.

## 2. Global Specifications & System-Wide Principles

This section defines the rules, conventions, and boilerplate that apply uniformly across the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, declaring the operator's capacity. A request with either header missing or empty, or whose role value is not one of the declared roles, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). The system recognizes exactly five roles: `Registrar`, `FinancialCounselor`, `UtilizationReviewer`, `ClearanceSupervisor`, and `SystemAdmin`. Each operation is restricted to a named set of roles (see §4); a caller whose role is valid but not listed for the endpoint is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403).

For every role — `Registrar`, `FinancialCounselor`, `UtilizationReviewer`, `ClearanceSupervisor`, and `SystemAdmin` alike — `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server never compares `X-User-ID` to any resource's `id`. It does, however, record the identifier for accountability: an authorization stores its creator as `requested_by_user_id` and its latest deciding reviewer as `decided_by_user_id`, and an escalation stores its opener as `opened_by_user_id` and its approver or rejecter as `decided_by_user_id`. These recorded identifiers are what the segregation-of-duties rules in §2.9 compare against.

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

List endpoints paginate through two query parameters. `limit` sets the maximum number of items returned: it defaults to 10 when omitted, accepts a minimum of 1, and is capped at a maximum of 100. `offset` sets the number of items skipped and defaults to 0. The `meta` object of a list response carries `limit`, `offset`, `total_count`, and `has_more`. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order.

Several list endpoints accept optional equality filters alongside pagination: the payer-contract list filters by `payer_code`; the eligibility-snapshot list filters by `patient_id`, `payer_code`, or `status`; the case list filters by `patient_id` or `status`; and the estimate list filters by `case_id`, `eligibility_snapshot_id`, or `status`.

### 2.4. Money, Dates, and the Logical Clock

All monetary fields in the system are integer cents — a value of `1000000` means ten thousand dollars. All percentage fields are integer percent in the range 0 to 100. Calendar dates are ISO `YYYY-MM-DD` strings; datetimes are ISO 8601 UTC with three fractional digits. One deliberate exception: the variance percentage `variance_pct` is a decimal number carried to two decimal places, because tolerance banding at ten percent requires sub-percent resolution.

Two time-related concepts recur throughout the document. First, a **business day** is any Monday through Friday; the system keeps no holiday calendar. When a rule speaks of the number of business days between a date A and a later date B, it means the count of weekdays that fall strictly after A and on or before B. Second, the server never reads wall-clock time. All "current time" semantics come from a **logical clock** whose startup default, before anyone has set it, is exactly `2026-08-01T00:00:00Z`. A `SystemAdmin`-only capability advances the logical clock to a supplied `to_iso8601` instant, and every advance runs the time-driven sweep: eligibility snapshots more than 30 days past their verification become `STALE`, `APPROVED` authorizations whose validity window has passed become `EXPIRED`, `PRESENTED` estimates whose service date has passed become `EXPIRED`, and payment plans with an installment more than fourteen days past due become `DEFAULTED`. The sweep response reports the new `current_utc` alongside the counts `staled_snapshots`, `expired_authorizations`, `expired_estimates`, and `defaulted_plans`. Each transition the sweep performs is detailed in §3 alongside the entity it affects.

### 2.5. Common Resource Properties

Every entity in the system — patients, charge items, payer contracts, contract rates, eligibility snapshots, clearance cases, estimates, authorizations, payment plans, deposits, variance records, and escalations — carries a standard set of system-managed fields:

- `id` (string): a server-minted UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, fixed at creation.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource — including mutations caused by cascading side effects originating on another resource.
- `version` (integer): starts at 1 at creation and increments by exactly 1 on every mutation, again including cascade-driven mutations. This field backs the optimistic concurrency control described in §2.6.

### 2.6. Optimistic Concurrency Control on Parent Versions

Two creation endpoints are guarded against stale client views of the parent resource, and both reject a mismatch with `ERR_STALE_VERSION` (HTTP 412).

When a `Registrar` captures an eligibility snapshot for a patient, the request must carry `expected_patient_version` equal to the patient record's current `version`. If another writer has advanced the patient's version since the client last read it — most commonly by capturing a newer snapshot, which itself increments the patient's `version` by 1 — the create is rejected with `ERR_STALE_VERSION`, preventing the client from superseding a verification it has never observed.

When a `FinancialCounselor` creates an estimate revision on a clearance case, the request must carry `expected_case_version` equal to the case's current `version`. Estimate creation increments the case's `version` by 1 and legitimately supersedes the prior non-locked estimate, so a client holding a stale case version is rejected with `ERR_STALE_VERSION` rather than being allowed to overwrite revisions it has not seen.

Endpoints other than these two do not accept a version field; all other optimistic-concurrency concerns are out of scope.

### 2.7. Nested Resource Retrieval

Many endpoints address a child resource through its parent — a rate under a payer contract, a snapshot under a patient, an estimate under a case. The system validates path identifiers strictly left to right: the first identifier in the path that does not correspond to an existing resource determines the failure, and the request is rejected with `ERR_NOT_FOUND` (HTTP 404) before any later identifier or any business rule is examined. A request to price an estimate under a case that does not exist therefore fails on the case, not on the estimate.

### 2.8. Validation Pipeline and Check Ordering

When several checks could reject the same request, the system applies them in a fixed pipeline so that the surfaced error is deterministic. The order is: (1) user-context headers, then (2) role authorization, then (3) left-to-right path existence, then (4) request-body shape — required fields present, types correct, enum values in range, amounts positive where required, and structural rules such as installment counts and date-window ordering — then (5) the optimistic-concurrency version check, then (6) state-machine legality of the requested transition, then (7) segregation of duties, and finally (8) domain business rules in their own declared priority.

Within the business-rule tier, ordering matters at four call sites and is stated here once, globally:

- At estimate creation, the version check precedes all business rules; among those, CPT-code existence (`ERR_UNKNOWN_CPT_CODE`) is evaluated first, then snapshot-patient matching (`ERR_SNAPSHOT_PATIENT_MISMATCH`), and the estimate-lock rule (`ERR_ESTIMATE_LOCKED`) last.
- At pricing, eligibility freshness (`ERR_SNAPSHOT_STALE`) is evaluated first, then CPT-code existence, then snapshot-patient matching, then contract presence (`ERR_NO_ACTIVE_CONTRACT`), and finally per-line rate coverage (`ERR_RATE_NOT_FOUND`).
- At authorization decision, state legality and segregation of duties are settled before the medical-necessity consistency rule (`ERR_MEDICAL_NECESSITY_CONFLICT`) is examined.
- At case clearance, the compliance gate (`ERR_AUTH_NOT_SATISFIED`) precedes both escalation gates — the missing-high-dollar-approval gate (`ERR_ESCALATION_REQUIRED`) before the open-escalation gate (`ERR_ESCALATION_PENDING`) — and the fiscal deposit gate (`ERR_DEPOSIT_SHORTFALL`) is evaluated last.

### 2.9. Segregation of Duties

Deciding and requesting must never be the same hand. An authorization decision is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403) when the deciding reviewer's `X-User-ID` equals the requesting reviewer's recorded `requested_by_user_id`. The same rule binds escalation closure: approving or rejecting an escalation is rejected with `ERR_SEGREGATION_OF_DUTIES` when the decider's `X-User-ID` equals the escalation's `opened_by_user_id`. There is exactly one exemption: escalations opened automatically by the system carry the literal string `"system"` as their `opened_by_user_id`, and any supervisor may decide them.

### 2.10. Case Posture and Hierarchical Recomputation

The clearance case is the aggregate root of the workflow, and a family of computed fields on it is kept continuously in sync with events on its children — estimates, deposits, authorizations, escalations, and payment plans. Whenever a child event changes the inputs to one of these derived values, the server recomputes the case immediately, within the same operation; every such recomputation is a mutation of the case and therefore refreshes its `updated_at` and increments its `version`. The headline derived field is `clearance_posture`, which reads `READY` only when three conditions all hold — `auth_satisfied`, `deposit_satisfied`, and `escalation_cleared` — and reads `BLOCKED` otherwise. The individual definitions of those three gates, and of the remaining computed fields, live with the workflows that feed them in §3. The general principle is that no client ever writes these fields; they are always the server's own projection of the case's children.

### 2.11. Precision and Rounding

All money arithmetic is performed in integer cents. Wherever a rule requires rounding, the method is **round half up** to the nearest whole cent, applied at exactly the step the rule names — no earlier and no later. Three rounding orders are pinned and non-substitutable. Under a multiple-procedure-reduction contract, the secondary-procedure adjustment is rounded per line *before* the quantity is multiplied in. Under insured benefit application, coinsurance is rounded per line and only then summed — rounding coinsurance once on the aggregate base is a documented trap and is not canonical. Payment-plan installment amounts are produced by a single floor division with the remainder placed on the final installment; rounding each installment half-up independently is a documented trap that can push the schedule's total above the financed principal. The one non-integer money-adjacent quantity, `variance_pct`, is rounded half up to two decimal places.

## 3. Business Logic & Workflows

### 3.1. Charge Master, Payer Contracts, and Rate Windows

Configuration begins with the charge master. A `SystemAdmin` registers each billable procedure as a charge item carrying a `cpt_code`, a free-text `description`, a `list_price_cents` greater than zero, and a `requires_auth_prior` flag marking CPT codes that trigger prior-authorization requirements in insured cases. The `cpt_code` is unique across the charge master, and every other part of the system that names a CPT code — estimate lines, contract rates, authorization requests — resolves against this list: an unknown code is rejected with `ERR_UNKNOWN_CPT_CODE` (HTTP 422).

A payer contract, also maintained by `SystemAdmin`, records a unique `payer_code`, a display `payer_name`, and a `bundling_rule` of either `NONE` or `MULTIPLE_PROCEDURE_REDUCTION`. The contract's `reduction_pct` governs how secondary procedures are paid under the reduction rule — a value of 50 means secondary lines are paid at fifty percent — and is required to lie between 1 and 99 inclusive when the bundling rule is `MULTIPLE_PROCEDURE_REDUCTION`; under `NONE` it is ignored and defaults to 0.

Each contract accumulates contracted rates over time. Adding a rate to a contract supplies the `cpt_code` it covers — which must already exist as a charge item — a `rate_cents` per-unit amount greater than zero, an `effective_from` date, and optionally an `effective_to` date. Rate windows are half-open: the window starts on `effective_from` inclusively and ends on `effective_to` exclusively, and a null `effective_to` leaves the window open-ended. When present, `effective_to` must be strictly later than `effective_from`, and windows for the same contract and CPT code must never overlap — though windows that merely touch, where the new window starts exactly on the day an existing window ends, are legitimate adjacency and allowed. An overlapping submission is rejected with `ERR_RATE_WINDOW_OVERLAP` (HTTP 409). Each stored rate records its owning contract as `contract_id`.

### 3.2. Patient Registration and Eligibility Verification

A `Registrar` registers each patient with a medical record number `mrn`, a `full_name`, and a `date_of_birth`. The `mrn` is unique across patients; a duplicate registration is rejected with `ERR_DUPLICATE_MRN` (HTTP 409).

Eligibility verification is captured as a snapshot rather than a mutable record, so that historical pricing decisions remain explainable. Capturing a snapshot supplies the `payer_code`, the subscriber `member_id`, the annual `deductible_total_cents` (zero or more), the `deductible_met_cents` already accumulated (between zero and the total, inclusive), the `oop_max_cents` out-of-pocket maximum (greater than zero), the `oop_met_cents` already accumulated (between zero and the maximum, inclusive), and the patient's `coinsurance_pct` after deductible (0 to 100). The request is OCC-guarded by `expected_patient_version` as described in §2.6, and a successful capture stamps `verified_at` with the current logical time, marks the snapshot `ACTIVE`, links it to the patient via `patient_id`, and increments the patient record's `version` by 1.

Only one snapshot per patient-and-payer combination is current at a time: creating a snapshot flips any prior `ACTIVE` snapshot for the same patient and `payer_code` to `SUPERSEDED`. Independently, the logical-clock sweep ages verifications out — a snapshot becomes `STALE` when the current logical time is strictly later than thirty days after its `verified_at`; at exactly the thirty-day mark it is still `ACTIVE`. `SUPERSEDED` and `STALE` are terminal. Pricing an insured estimate requires a snapshot that is both `ACTIVE` and within that thirty-day freshness window, and violations surface as `ERR_SNAPSHOT_STALE` (HTTP 409).

### 3.3. Opening the Financial Clearance Case

A scheduled service becomes a financial clearance case when a `Registrar` or `FinancialCounselor` opens one for a registered patient, supplying the `service_date` and a free-text `service_description`. The case begins in `OPEN` status with its derived fields at neutral defaults: `active_estimate_id` null, `auth_required` and the other boolean flags false, and its money counters at zero.

The case's computed fields, recomputed per §2.10 as child events arrive, are the operational heart of the clearance desk:

- `active_estimate_id` names the latest estimate on the case that is not superseded, cancelled, or expired — null when no such estimate exists.
- `auth_required` is true when the active estimate is priced in `INSURED` mode and at least one of its lines resolves to a charge item whose `requires_auth_prior` flag is true; it is false in every other situation.
- `auth_satisfied` is true when `auth_required` is false, or when an authorization on the case is `APPROVED`, has not since expired, and its closed validity window covers the case's `service_date` — that is, `valid_from` on or before the service date and `valid_to` on or after it.
- `required_deposit_cents` is zero until an estimate on the case is accepted, and thereafter is twenty-five percent of the accepted estimate's `patient_responsibility_cents`, rounded half up to a whole cent.
- `deposit_posted_cents` is a ledger: the sum of `amount_cents` over the case's deposits currently in `POSTED` status.
- `deposit_satisfied` is true when the active estimate is `FINALIZED`, or when the posted ledger meets or exceeds `required_deposit_cents` while an estimate stands `ACCEPTED` or `FINALIZED`.
- `high_dollar_flag` is true when the active estimate's `patient_responsibility_cents` met or exceeded one million cents — ten thousand dollars — at its most recent pricing.
- `escalation_cleared` is true when no escalation on the case is `OPEN` and, in addition, either the case is not high-dollar or an `APPROVED` high-dollar escalation exists for the active estimate.
- `clearance_posture` collapses the three gates: `READY` when `auth_satisfied` and `deposit_satisfied` and `escalation_cleared` all hold, `BLOCKED` otherwise.

### 3.4. Estimate Revisions and Pricing

A `FinancialCounselor` builds the patient estimate as a sequence of revisions on the case. Creating an estimate specifies a `pricing_mode` of `INSURED` or `UNINSURED_GFE`, an array of `lines` each pairing a `cpt_code` with an integer `quantity` of at least 1, and — for insured pricing only — an `eligibility_snapshot_id` linking the snapshot captured at verification. The snapshot link is required in `INSURED` mode and forbidden in `UNINSURED_GFE` mode; either violation, like any other body-shape failure, is an `ERR_INVALID_REQUEST` (HTTP 400). Every line's code must exist in the charge master (`ERR_UNKNOWN_CPT_CODE`), and an insured estimate's snapshot must belong to the same patient as the case (`ERR_SNAPSHOT_PATIENT_MISMATCH`, HTTP 422).

Creation is guarded by `expected_case_version` per §2.6, and the estimate set locks upon acceptance: once any estimate on the case stands `ACCEPTED` or `FINALIZED`, creating another revision is rejected with `ERR_ESTIMATE_LOCKED` (HTTP 409). Otherwise the new estimate starts in `DRAFT`, receives a `revision` number one higher than the case's previous estimate (1 for the first), and supersedes the prior revision — any estimate of the case in `DRAFT`, `PRICED`, or `PRESENTED` moves to `SUPERSEDED`. Supersession is deliberately quiet: it carries no case-level financial side effects, no deposit requirement, no status change on the case. Creation does increment the case's `version` by 1. An estimate's full lifecycle runs `DRAFT` → `PRICED` → `PRESENTED` → `ACCEPTED` → `FINALIZED`, with `SUPERSEDED`, `EXPIRED`, and `CANCELLED` as the other terminal outcomes; terminal estimates are locked against every further transition, and any transition attempted from a state that does not offer it is `ERR_INVALID_STATE` (HTTP 409).

Pricing a `DRAFT` estimate is where the two pricing modes diverge, but both paths share the entry checks ordered as in §2.8: for insured pricing the linked snapshot must belong to the case's patient and be `ACTIVE` and within the thirty-day freshness window (`ERR_SNAPSHOT_STALE`), every line code must exist in the charge master, a payer contract must exist for the snapshot's `payer_code` (`ERR_NO_ACTIVE_CONTRACT`, HTTP 422), and every line's CPT code must have a contract rate whose half-open window covers the case's `service_date` (`ERR_RATE_NOT_FOUND`, HTTP 422).

**Insured contracted pricing.** Each line's `unit_rate_cents` is the `rate_cents` of the matching contract rate — the one belonging to the contract whose `payer_code` equals the snapshot's, whose `effective_from` is on or before the service date, and which has no `effective_to` or an `effective_to` strictly after the service date. When the contract's `bundling_rule` is `NONE`, every line's `line_amount_cents` is simply its quantity times its unit rate. When the rule is `MULTIPLE_PROCEDURE_REDUCTION`, the lines are first ranked: highest `unit_rate_cents` first, ties broken by `cpt_code` in ascending alphabetical order, remaining ties broken by input line order — never by any record id. The top-ranked line is the primary procedure and keeps its full unit rate. Every lower-ranked line is a secondary procedure whose adjusted unit rate is its unit rate times the contract's `reduction_pct` percent, rounded half up to a whole cent — this rounding happens per line, before the quantity is multiplied in — and each line's `line_amount_cents` is then its quantity times its adjusted rate. The estimate's `allowed_amount_cents` is the sum of the line amounts.

**Insured benefit application.** Patient responsibility is then accumulated per line, processing lines in `cpt_code` ascending order with input order as the final tie-break, against the linked snapshot. The running deductible remainder starts at the snapshot's `deductible_total_cents` minus its `deductible_met_cents`, floored at zero. For each line in order: the portion sent to deductible is the smaller of the line's amount and the remaining deductible; the remainder is decremented accordingly; and the line's coinsurance is the line amount minus its deductible portion, multiplied by `coinsurance_pct` percent, rounded half up to a whole cent per line. The estimate's `deductible_applied_cents` is the sum of the per-line deductible portions, and its `coinsurance_cents` is the sum of the per-line coinsurance figures — rounding coinsurance once on the aggregate base is not canonical. The out-of-pocket cap applies last: the remaining out-of-pocket room is `oop_max_cents` minus `oop_met_cents`, floored at zero, and `patient_responsibility_cents` is the smaller of the deductible-plus-coinsurance total and that remaining room. `insurance_pays_cents` is the allowed amount minus the patient responsibility.

**Uninsured good-faith pricing.** In `UNINSURED_GFE` mode the same lines price off the charge master instead of a contract: each line's gross is its quantity times the charge item's `list_price_cents`; each line's discount is that gross times the configured uninsured-discount percentage, rounded half up per line; and `gfe_total_cents` is the sum of each line's gross minus its discount. The patient responsibility equals `gfe_total_cents`, `allowed_amount_cents` records the undiscounted list subtotal, and `deductible_applied_cents`, `coinsurance_cents`, and `insurance_pays_cents` are all zero. Identical lines priced under the two modes therefore legitimately produce different patient responsibilities.

**High-dollar screening.** After pricing computes `patient_responsibility_cents`, the estimate's own `high_dollar_flag` is set: the threshold is one million cents — ten thousand dollars — and an estimate at exactly the threshold counts as high-dollar. When the flag comes up true, the system opens a high-dollar escalation against the estimate, marked `OPEN`, recorded as opened by the literal string `"system"`, carrying `trigger_amount_cents` equal to the patient responsibility — unless such an escalation is already `OPEN` for that estimate, in which case no duplicate is created. The case's `high_dollar_flag` is updated from the estimate's flag at the same time.

### 3.5. The Good-Faith Clock, Presentation, and Acceptance

Uninsured estimates carry a federal-style delivery timeline computed the moment the estimate is created. Let the creation date be the logical date at creation and S be the case's `service_date`, and count the business days between them as defined in §2.4. When at least ten business days separate creation from service, the estimate must be delivered to the patient within three business days; when at least three but fewer than ten business days separate them, the delivery window shrinks to one business day; when fewer than three business days separate them, no good-faith estimate is mandated at all — `gfe_required` is false and `gfe_delivery_deadline` is null. Otherwise `gfe_required` is true and `gfe_delivery_deadline` is the end of day — 23:59:59.999 UTC — of the date reached by adding the applicable number of business days to the creation date, skipping weekends. Presenting an estimate whose good-faith deadline has passed is rejected with `ERR_GFE_DEADLINE_MISSED` (HTTP 409). Insured estimates carry no such timeline: `gfe_required` and `gfe_delivery_deadline` apply to the uninsured variant only.

Presentation moves a `PRICED` estimate to `PRESENTED` and stamps `presented_at` with the current logical time on first arrival. The first estimate on a case to reach `PRESENTED` also writes the case-level pin `first_presented_patient_resp_cents`, capturing the patient responsibility the patient was first shown; this value is written once and never overwritten by later revisions. Should the service date pass with an estimate still sitting in `PRESENTED`, the logical-clock sweep moves it to `EXPIRED`.

Acceptance records the patient's agreement and moves `PRESENTED` → `ACCEPTED`, stamping `accepted_at`. Acceptance is the pivot point of the whole case: the estimate becomes the case's `active_estimate_id`; the case's `required_deposit_cents` is set to twenty-five percent of the accepted `patient_responsibility_cents`, rounded half up; `auth_required` is recomputed from the accepted estimate's lines; the case's `high_dollar_flag` adopts the estimate's flag; and a case still sitting in `OPEN` automatically advances to `IN_REVIEW`. From this point the estimate set is locked (§3.4) and the clearance gates begin to bind.

### 3.6. Deposits and the Prepayment Ledger

Prepayments secure the case against the deposit requirement. A `FinancialCounselor` pledges a deposit with an `amount_cents` greater than zero and a `method` of `CARD`, `CHECK`, or `CASH`; the pledge starts in `PLEDGED`. Posting the deposit — also a counselor action — moves `PLEDGED` → `POSTED`, stamps `posted_at`, and syncs the ledger: the case's `deposit_posted_cents` increases by the deposit's amount and `deposit_satisfied` is recomputed. Only `POSTED` deposits count toward the requirement, and only a `POSTED` deposit can be refunded — attempting the refund transition on a deposit in any other state is `ERR_INVALID_STATE`.

Refunds, executed by a `ClearanceSupervisor`, follow a business-day schedule measured from the current logical date to the case's `service_date`. When at least two business days remain before service, the patient receives a full refund of the pledged amount — exactly two business days out still qualifies for the full amount. When exactly one business day remains, the refund is fifty percent of the amount, rounded half up to a whole cent. On the day of service or later, the deposit is forfeit and the refund is zero. The refund lands in `refund_amount_cents` with `refund_reason` set to `SERVICE_CANCELLED`, the deposit moves to `REFUNDED`, and — crucially — the case's `deposit_posted_cents` decreases by the deposit's full `amount_cents`, not by the refunded portion: any retained cancellation fee leaves the deposit ledger entirely. That ledger reduction recomputes `deposit_satisfied`, and if the case was `CLEARED` and the requirement is no longer met, the case automatically regresses to `IN_REVIEW` with `clearance_posture` back to `BLOCKED`.

### 3.7. Prior Authorization and Medical Necessity

When the active estimate's pricing mode is `INSURED` and any of its lines resolves to a charge item flagged `requires_auth_prior`, the case's `auth_required` is true and a `UtilizationReviewer` must obtain payer approval before clearance. Requesting an authorization supplies the `payer_code` being asked and a non-empty `cpt_codes` array; the request starts in `REQUESTED` status with `requested_by_user_id` set to the caller's `X-User-ID`. Duplication is refused: if any requested CPT code intersects the codes of an existing `APPROVED`, non-expired authorization on the same case whose closed validity window contains the case's `service_date`, the request is rejected with `ERR_AUTH_ALREADY_COVERED` (HTTP 409).

Deciding an authorization is a separate `UtilizationReviewer` act governed by segregation of duties (§2.9). The decision payload carries `decision`, the reviewer's `medical_necessity_met` determination, and — for approvals — the `valid_from` and `valid_to` dates. Consistency between the decision and the medical-necessity flag is enforced: an approval requires `medical_necessity_met` true, and a denial requires it false; a mismatch is `ERR_MEDICAL_NECESSITY_CONFLICT` (HTTP 422). Approvals additionally require both validity dates, with `valid_to` on or after `valid_from` — missing or inverted dates are `ERR_INVALID_REQUEST`. From `REQUESTED`, a decision of `APPROVED` mints an `auth_number` (a sequential identifier of the form `AUTH-<number>`), records `decided_by_user_id`, and recomputes the case's `auth_satisfied`; a decision of `DENIED` records the decider and leaves the authorization appealable.

The appeal cycle runs `DENIED` → `APPEALED` → a second decision. From `APPEALED`, an approval follows the same rules as a first-pass approval — necessity met, validity dates present, segregation of duties, `auth_number` minted, `auth_satisfied` recomputed — while a denial becomes `DENIED_FINAL`, which is terminal. `DENIED_FINAL`, `WITHDRAWN`, and `EXPIRED` are the terminal states; any decide attempted on an authorization no longer in `REQUESTED` or `APPEALED` is `ERR_INVALID_STATE`.

Approval is not permanent. The logical-clock sweep expires an `APPROVED` authorization when the current logical date falls strictly after its `valid_to`, moving it to `EXPIRED`; the case's `auth_satisfied` is recomputed, and if the case was `CLEARED` it regresses to `IN_REVIEW`. Case cancellation withdraws any authorization still in `REQUESTED` or `APPEALED`, moving it to `WITHDRAWN`.

### 3.8. Payment Plans and Collections

Patients who cannot settle their responsibility at once are offered installment financing. A `FinancialCounselor` drafts a plan with a `principal_cents` greater than zero and a `num_installments` between 2 and 12 inclusive; values outside that range are `ERR_INVALID_REQUEST`. The draft starts in `DRAFT` with its installment amounts computed immediately by a single floor division: `installment_amount_cents` is the principal divided by the number of installments, truncated; installments 1 through N−1 each carry that amount; and the final installment N carries the remainder — the principal minus N−1 times the base amount — so that the schedule always sums exactly to `principal_cents`. Rounding each installment half-up instead is a documented trap that can push the total above the principal and is not canonical. Each installment entry in `installments` carries a `seq`, a `due_date`, an `amount_cents`, a running `paid_cents`, and a `status` of `PENDING` or `PAID`; amounts are fixed at creation while due dates are fixed later, at activation.

Activation moves `DRAFT` → `ACTIVE` and is only possible once the case holds an estimate in `ACCEPTED` or `FINALIZED` status — otherwise `ERR_NO_ACCEPTED_ESTIMATE` (HTTP 409). Activation fixes the calendar: the first `due_date` falls thirty days after the activation date, and each subsequent installment falls one calendar month after its predecessor, with the day clamped to the end of the month when the target month is shorter.

Payments against an `ACTIVE` or `DEFAULTED` plan follow a strict waterfall. A payment supplies `amount_cents`; an amount exceeding the plan's `principal_outstanding_cents` is rejected outright with `ERR_PAYMENT_EXCEEDS_OUTSTANDING` (HTTP 422). The payment then applies to installments in `due_date` ascending order, ties broken by `seq` ascending: each installment in turn receives the smaller of the remaining payment and its own unpaid balance, its `paid_cents` rises accordingly, and an installment whose `paid_cents` reaches its `amount_cents` flips to `PAID`. The plan's `principal_outstanding_cents` — the principal minus all `paid_cents` across installments — is recomputed, and when it reaches zero the plan completes itself, moving `ACTIVE` → `COMPLETED`.

Collections risk is tracked on the logical clock. The plan's `missed_payment_count` is the number of installments still `PENDING` whose `due_date` is strictly before the current logical date. The sweep moves `ACTIVE` → `DEFAULTED` when any installment remains `PENDING` more than fourteen days past its due date — that is, when the due date plus fourteen days falls strictly before the current logical date — and recomputes the missed count. Default is not terminal: a counselor reinstates the plan with a `cure_amount_cents` that must at least cover the sum of the unpaid balances — `amount_cents` minus `paid_cents` — over all installments whose due date is strictly past. A short cure is rejected with `ERR_CURE_INSUFFICIENT` (HTTP 409); a sufficient one is applied through the same payment waterfall, the missed count is recomputed, and the plan returns `DEFAULTED` → `ACTIVE`. The default–reinstate cycle may repeat as often as events require. `COMPLETED` and `CANCELLED` are the plan's terminal states.

### 3.9. Escalations, Finalization, Clearance, and Cancellation

**Escalations** route exceptions to a `ClearanceSupervisor`. Three reasons exist: `HIGH_DOLLAR`, `AUTH_EXCEPTION`, and `GFE_DISPUTE`. High-dollar escalations are usually automatic, opened at pricing time as described in §3.4; good-faith dispute escalations are automatic at finalize time, described below; and counselors or supervisors may also open any of the three manually, supplying the `reason`, an optional `estimate_id`, and an optional `note`. A manual open records `opened_by_user_id` as the caller's `X-User-ID`; automatic ones record the literal string `"system"`. The `estimate_id` link is set for high-dollar and dispute escalations and is null for case-level authorization exceptions; `trigger_amount_cents` records the patient responsibility that tripped the high-dollar threshold, or the variance overage behind a dispute, and is zero for authorization exceptions. Every escalation starts `OPEN`, and an open escalation immediately blocks clearance because `escalation_cleared` recomputes to false. A supervisor closes an escalation by approving it, moving `OPEN` → `APPROVED`, or rejecting it, moving `OPEN` → `REJECTED` — both terminal — optionally recording a `decision_note`; segregation of duties (§2.9) bars the opener from deciding their own escalation, with the `"system"` exemption. Either decision recomputes the case's `escalation_cleared`.

**Finalization** happens after the service, when a `FinancialCounselor` or `ClearanceSupervisor` records the actual billed patient amount `finalized_actual_billed_cents` — which must be greater than zero, else `ERR_INVALID_REQUEST` — moving the `ACCEPTED` estimate to `FINALIZED`. Finalization fans out into three cascades.

First, a variance record is created for the estimate, capturing both accuracy baselines: `baseline_first_presented_resp_cents` copies the case-level pin of what the patient was first shown, and `baseline_last_accepted_resp_cents` copies the accepted estimate's `patient_responsibility_cents`; `actual_billed_cents` copies the just-recorded actual, and `estimate_id` links the record to its estimate. The signed differences are `variance_vs_first_cents` against the first-shown baseline and `variance_vs_accepted_cents` against the accepted baseline. The percentage `variance_pct` is the absolute value of the accepted-baseline difference, expressed as a percentage of the accepted baseline, rounded half up to two decimal places; when the accepted baseline is zero the percentage is defined as 0.0 if the actual is also zero, else 100.0. The `classification` is `WITHIN_TOLERANCE` when that percentage is at most 10.00 — the boundary is inclusive — `OVER_TOLERANCE` when the actual exceeded the accepted baseline and the percentage is above 10.00, and `UNDER_TOLERANCE` when the actual fell short and the percentage is above 10.00. Exactly one variance record is created per finalize. It begins `UNREVIEWED`; a `ClearanceSupervisor` later marks it `REVIEWED` by supplying a non-empty `root_cause` — an empty cause is `ERR_INVALID_REQUEST`.

Second, for uninsured estimates only, dispute eligibility is decided: the estimate's `dispute_eligible` is true when the actual billed amount exceeds `gfe_total_cents` by at least forty thousand cents — four hundred dollars, with the exact threshold amount qualifying — and insured estimates always compute `dispute_eligible` false. When the flag is true, the new variance record triggers the system to open a `GFE_DISPUTE` escalation: `OPEN`, opened by `"system"`, linked to the finalized estimate, carrying `trigger_amount_cents` equal to `variance_vs_accepted_cents`. That fresh `OPEN` escalation flips the case's `escalation_cleared` to false, and a `CLEARED` case regresses to `IN_REVIEW`. The variance record carries its own copy of `dispute_eligible` for reporting.

Third, posted deposits are applied to the bill. Each of the case's `POSTED` deposits, oldest `created_at` first, applies up to the remaining actual billed amount: the deposit's `applied_amount_cents` is the smaller of its `amount_cents` and the bill remaining at its turn. A deposit whose amount exceeds the remaining bill keeps status `APPLIED` with the excess returned in `refund_amount_cents` under `refund_reason` `OVERPAYMENT`. A deposit reached when nothing of the bill remains — applying zero — instead becomes `REFUNDED` with its full amount in `refund_amount_cents`, again under `OVERPAYMENT`. When the cascade settles, every resolved deposit has left `POSTED` and the case's `deposit_posted_cents` ledger is recomputed accordingly.

**Clearance** is the supervisor's affirmative act. Clearing is offered from `IN_REVIEW` — attempting it on a case already `CLEARED` or `CANCELLED` is `ERR_INVALID_STATE` — and evaluates three gates in the fixed order of §2.8. The compliance gate comes first: if `auth_satisfied` is false, the clear is rejected with `ERR_AUTH_NOT_SATISFIED` (HTTP 409). The escalation gates come next: a high-dollar case with neither an `APPROVED` high-dollar escalation for the active estimate nor one still `OPEN` — for instance after a rejection — is rejected with `ERR_ESCALATION_REQUIRED` (HTTP 409), and any escalation still `OPEN`, whatever its reason, is rejected with `ERR_ESCALATION_PENDING` (HTTP 409). The fiscal gate comes last: when `deposit_posted_cents` falls short of `required_deposit_cents`, the clear is rejected with `ERR_DEPOSIT_SHORTFALL` (HTTP 409). When all three gates pass, the case moves `IN_REVIEW` → `CLEARED`.

Clearance is reversible. A case in `CLEARED` regresses to `IN_REVIEW` — with `clearance_posture` recomputed to `BLOCKED` — when any of three things happens: a deposit refund breaks `deposit_satisfied` (§3.6), the sweep expires an `APPROVED` authorization that the case relied on (§3.7), or a new escalation opens, including the automatic dispute escalation at finalize.

**Cancellation** is available to a `ClearanceSupervisor` from `OPEN`, `IN_REVIEW`, or `CLEARED`, with one hard stop: a case carrying a `FINALIZED` estimate can no longer be cancelled — the attempt is `ERR_INVALID_STATE`. Cancellation cascades through every child collection: estimates in `DRAFT`, `PRICED`, or `PRESENTED` move to `CANCELLED`; deposits still `PLEDGED` move to `CANCELLED`; deposits in `POSTED` move to `REFUNDED` with the refund computed by the business-day schedule of §3.6 under `refund_reason` `SERVICE_CANCELLED`, and the case's `deposit_posted_cents` reduced by each refunded deposit's full amount; authorizations in `REQUESTED` or `APPEALED` move to `WITHDRAWN`; and payment plans in `DRAFT`, `ACTIVE`, or `DEFAULTED` move to `CANCELLED`. `CANCELLED` is terminal for the case.

## 4. Endpoint Definitions

All endpoints are mounted under the `/clearance` prefix. Operations that create a new resource return `201 Created`; operations that modify an existing resource — transitions, decisions, sweeps — return `200 OK`. Request and response payloads follow the envelope of §2.2, and the business rules behind each operation are defined in §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/clearance/charge-items` | Create a charge-master item (CPT list price + prior-auth flag) | SystemAdmin |
| POST | `/clearance/payer-contracts` | Create a payer contract (bundling policy per payer_code) | SystemAdmin |
| GET | `/clearance/payer-contracts/{id}` | Get a payer contract | Registrar, FinancialCounselor, UtilizationReviewer, ClearanceSupervisor, SystemAdmin |
| GET | `/clearance/payer-contracts` | List payer contracts (filterable by payer_code) | Registrar, FinancialCounselor, UtilizationReviewer, ClearanceSupervisor, SystemAdmin |
| POST | `/clearance/payer-contracts/{id}/rates` | Add a contracted rate window for a CPT; half-open overlap rejected | SystemAdmin |
| GET | `/clearance/payer-contracts/{id}/rates` | List rates of a contract | Registrar, FinancialCounselor, UtilizationReviewer, ClearanceSupervisor, SystemAdmin |
| POST | `/clearance/patients` | Register a patient | Registrar |
| GET | `/clearance/patients/{id}` | Get a patient | Registrar, FinancialCounselor, UtilizationReviewer, ClearanceSupervisor, SystemAdmin |
| POST | `/clearance/patients/{id}/eligibility-snapshots` | Capture an eligibility verification snapshot; supersedes the ACTIVE snapshot for the same (patient, payer_code); OCC-guarded on the patient version | Registrar |
| GET | `/clearance/eligibility-snapshots/{id}` | Get an eligibility snapshot | Registrar, FinancialCounselor, UtilizationReviewer, ClearanceSupervisor, SystemAdmin |
| GET | `/clearance/eligibility-snapshots` | List eligibility snapshots (filterable) | Registrar, FinancialCounselor, UtilizationReviewer, ClearanceSupervisor, SystemAdmin |
| POST | `/clearance/patients/{id}/cases` | Open a financial clearance case for a scheduled service | Registrar, FinancialCounselor |
| GET | `/clearance/cases/{id}` | Get a case (with computed clearance posture fields) | Registrar, FinancialCounselor, UtilizationReviewer, ClearanceSupervisor, SystemAdmin |
| GET | `/clearance/cases` | List cases (filterable) | Registrar, FinancialCounselor, UtilizationReviewer, ClearanceSupervisor, SystemAdmin |
| POST | `/clearance/cases/{id}/clear` | Attempt financial clearance; ordered gates: auth (compliance) then escalation then deposit (fiscal) | ClearanceSupervisor |
| POST | `/clearance/cases/{id}/cancel` | Cancel a case; cascades to estimates, deposits, authorizations, plans | ClearanceSupervisor |
| POST | `/clearance/cases/{id}/estimates` | Create an estimate revision for a case; supersedes the prior non-locked estimate; OCC-guarded on the case version | FinancialCounselor |
| GET | `/clearance/estimates/{id}` | Get an estimate | Registrar, FinancialCounselor, UtilizationReviewer, ClearanceSupervisor, SystemAdmin |
| GET | `/clearance/cases/{id}/estimates` | List estimates of a case (all revisions, including superseded) | Registrar, FinancialCounselor, UtilizationReviewer, ClearanceSupervisor, SystemAdmin |
| GET | `/clearance/estimates` | List estimates (filterable) | Registrar, FinancialCounselor, UtilizationReviewer, ClearanceSupervisor, SystemAdmin |
| POST | `/clearance/estimates/{id}/price` | Price a DRAFT estimate (contracted bundling + benefits, or good-faith list-less-discount) | FinancialCounselor |
| POST | `/clearance/estimates/{id}/present` | Present the estimate to the patient (delivery timestamp; good-faith deadline enforced) | FinancialCounselor |
| POST | `/clearance/estimates/{id}/accept` | Record patient acceptance; computes case deposit and authorization requirements | FinancialCounselor |
| POST | `/clearance/estimates/{id}/finalize` | Post-service: record actual billed amount; creates variance record; applies posted deposits; may auto-open a dispute escalation | FinancialCounselor, ClearanceSupervisor |
| POST | `/clearance/cases/{id}/authorizations` | Request prior authorization for CPT codes | UtilizationReviewer |
| GET | `/clearance/cases/{id}/authorizations` | List authorizations of a case | Registrar, FinancialCounselor, UtilizationReviewer, ClearanceSupervisor, SystemAdmin |
| POST | `/clearance/authorizations/{id}/decide` | Decide a REQUESTED or APPEALED authorization (segregation of duties applies) | UtilizationReviewer |
| POST | `/clearance/authorizations/{id}/appeal` | Appeal a DENIED authorization | UtilizationReviewer |
| POST | `/clearance/cases/{id}/payment-plans` | Draft a payment plan; installment amounts computed immediately (floor + remainder on last) | FinancialCounselor |
| GET | `/clearance/cases/{id}/payment-plans` | List payment plans of a case | Registrar, FinancialCounselor, UtilizationReviewer, ClearanceSupervisor, SystemAdmin |
| POST | `/clearance/payment-plans/{id}/activate` | Activate a draft plan (requires an accepted or finalized estimate on the case); fixes due dates | FinancialCounselor |
| POST | `/clearance/payment-plans/{id}/payments` | Record a payment; waterfall across installments by due date then sequence | FinancialCounselor |
| POST | `/clearance/payment-plans/{id}/reinstate` | Cure a defaulted plan; cure amount must cover all past-due unpaid balances | FinancialCounselor |
| POST | `/clearance/cases/{id}/deposits` | Pledge a prepayment/deposit | FinancialCounselor |
| GET | `/clearance/cases/{id}/deposits` | List deposits of a case | Registrar, FinancialCounselor, UtilizationReviewer, ClearanceSupervisor, SystemAdmin |
| POST | `/clearance/deposits/{id}/post` | Capture/post a pledged deposit; syncs the case deposit ledger | FinancialCounselor |
| POST | `/clearance/deposits/{id}/refund` | Refund a posted deposit per the business-day refund rule; may regress a cleared case | ClearanceSupervisor |
| GET | `/clearance/estimates/{id}/variance-records` | List variance records of an estimate | Registrar, FinancialCounselor, UtilizationReviewer, ClearanceSupervisor, SystemAdmin |
| POST | `/clearance/variance-records/{id}/review` | Mark a variance record reviewed with a root cause | ClearanceSupervisor |
| POST | `/clearance/cases/{id}/escalations` | Manually open an escalation (authorization exception, dispute, or high-dollar) | FinancialCounselor, ClearanceSupervisor |
| GET | `/clearance/cases/{id}/escalations` | List escalations of a case | Registrar, FinancialCounselor, UtilizationReviewer, ClearanceSupervisor, SystemAdmin |
| GET | `/clearance/estimates/{id}/escalations` | List escalations tied to an estimate | Registrar, FinancialCounselor, UtilizationReviewer, ClearanceSupervisor, SystemAdmin |
| POST | `/clearance/escalations/{id}/approve` | Approve an escalation (approver differs from opener unless system-opened) | ClearanceSupervisor |
| POST | `/clearance/escalations/{id}/reject` | Reject an escalation (same segregation rule as approve) | ClearanceSupervisor |
| POST | `/clearance/_clock/set_current_utc` | Set the logical clock and run the time-driven sweep (staleness, expiry, default) | SystemAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error are defined in the narratives of §2 and §3; this catalogue is the canonical id-to-status mapping.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN_FOR_ROLE` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_AUTH_NOT_SATISFIED` | 409 Conflict |
| `ERR_GFE_DEADLINE_MISSED` | 409 Conflict |
| `ERR_SNAPSHOT_STALE` | 409 Conflict |
| `ERR_UNKNOWN_CPT_CODE` | 422 Unprocessable Entity |
| `ERR_SNAPSHOT_PATIENT_MISMATCH` | 422 Unprocessable Entity |
| `ERR_NO_ACTIVE_CONTRACT` | 422 Unprocessable Entity |
| `ERR_RATE_NOT_FOUND` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_MRN` | 409 Conflict |
| `ERR_RATE_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_AUTH_ALREADY_COVERED` | 409 Conflict |
| `ERR_ESTIMATE_LOCKED` | 409 Conflict |
| `ERR_MEDICAL_NECESSITY_CONFLICT` | 422 Unprocessable Entity |
| `ERR_NO_ACCEPTED_ESTIMATE` | 409 Conflict |
| `ERR_ESCALATION_REQUIRED` | 409 Conflict |
| `ERR_ESCALATION_PENDING` | 409 Conflict |
| `ERR_DEPOSIT_SHORTFALL` | 409 Conflict |
| `ERR_PAYMENT_EXCEEDS_OUTSTANDING` | 422 Unprocessable Entity |
| `ERR_CURE_INSUFFICIENT` | 409 Conflict |
