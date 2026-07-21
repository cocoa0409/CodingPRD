# Catastrophe Adjuster API — Product Requirements Document

## 1. Introduction

Independent and catastrophe (CAT) adjusters are the field workforce that property carriers rely on when losses spike — a hurricane makes landfall, a hailstorm sweeps a metro, a wildfire threatens a county — and the carrier's own staff cannot absorb the surge. This document specifies the backend service that coordinates the entire arc of that work: onboarding adjusters and their multi-state licenses, standing up catastrophe events and staffing their deployment rosters, routing individual claims to licensed adjusters, capturing on-site inspections and Xactimate-style estimates, moving scope-and-photo reports through quality-assurance review, and finally billing and paying the adjuster against either a tiered fee schedule or a time-and-expense arrangement.

The system exists to keep two things simultaneously true under pressure: that only a properly licensed, properly assigned adjuster touches a given claim, and that every dollar promised against a claim's reserve is accounted for through a strict billing ledger. Because catastrophe response is intrinsically time-sensitive — licenses expire, deployment windows open and close, roster seats are finite — the service is driven by a controllable logical clock rather than wall-clock time, so that expiry boundaries, deployment activation windows, and payment timestamps are all deterministic. The remainder of this document defines the global contracts every endpoint honors (Section 2), the business workflows and their scattered rules (Section 3), the full endpoint surface (Section 4), and the error catalogue (Section 5).

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming that principal's role. If either header is absent, or if `X-User-Role` is not one of the five roles defined below, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). If the headers are well-formed but the named role is not permitted to perform the requested operation, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).

The five roles are spelled exactly as follows:

- **`DeskExaminer`** — the carrier's desk examiner. Opens claims, offers assignments, and reopens closed claims. When `X-User-Role` is `DeskExaminer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`.
- **`FieldAdjuster`** — the independent or CAT adjuster performing fieldwork. When `X-User-Role` is `FieldAdjuster`, `X-User-ID` is the `id` of the acting `Adjuster`; ownership checks on any assignment-scoped resource compare the parent `Assignment`'s `adjuster_id` to `X-User-ID`.
- **`QAReviewer`** — a senior adjuster who reviews reports. When `X-User-Role` is `QAReviewer`, `X-User-ID` is likewise the `id` of the acting `Adjuster`; this identity is what the segregation-of-duties rule tests against the report's authoring adjuster.
- **`LicensingAdmin`** — manages adjuster records, licenses, catastrophe events, and the deployment roster. When `X-User-Role` is `LicensingAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity.
- **`BillingManager`** — manages fee schedules and the fee-bill approval and payment lifecycle. When `X-User-Role` is `BillingManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity.

All five roles may call every read (GET) endpoint. Write operations are restricted; Section 4 names the authorized role(s) for each endpoint, and the ownership and segregation rules that further constrain the two entity-backed roles are described in Sections 2.9 and 3.5.

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

### 2.3. Pagination

All list endpoints accept two pagination query parameters, `limit` and `offset`. The `limit` defaults to 10 when omitted, with a minimum of 1 and a maximum of 100; a supplied value outside that range is invalid. The `offset` defaults to 0 and has a minimum of 0. List results are always ordered by `created_at` ascending — the oldest resource first. The `meta` block of a list response carries `limit`, `offset`, `total_count` (the total number of matching resources across all pages), and `has_more` (true when further resources exist beyond the current page).

### 2.4. The Logical Clock and Temporal Semantics

The service does not read wall-clock time. Instead it maintains a **logical clock** whose value can be set by an operator. Before any set call, the clock reads exactly its startup default of `2026-07-01T00:00:00Z`. An authorized operator may advance or rewind the clock by supplying a target instant as `to_iso8601`; the response reports the new value as `current_utc`. The logical clock is the single source of "now" for every time-dependent rule in this specification: license expiry, deployment activation windows, and the `paid_at` stamp on payments are all evaluated against it.

Two temporal conventions apply throughout. First, license currency is a strict comparison: a license is current only while the clock is strictly before its `expires_at`; the instant the clock reaches or passes `expires_at`, the license is no longer usable. Second, deployment and inspection windows are treated as **half-open** intervals `[start, end)` — the start instant is inclusive and the end instant is exclusive — which is why two windows that merely touch (one ending exactly when the next begins) do not conflict.

### 2.5. Common Resource Properties and Versioning

Every persisted resource carries a server-minted `id` that is a UUID with no type prefix, and a `created_at` timestamp in ISO 8601 UTC with three fractional digits. Most resources additionally carry an `updated_at` timestamp (same format, refreshed on every mutation) and an integer `version` that begins at 1 and increments by 1 on each mutation. Two resource types are the exception: **time entries** and **payments** are immutable ledger records that carry only `id` and `created_at` — they have no `updated_at` and no `version`.

Whenever an operation mutates a resource, its `updated_at` is refreshed and its `version` is incremented. This applies to cascade targets as well: when one operation drives a state change on a related resource, that related resource's `updated_at` and `version` advance too. The `version` field is also the anchor for the optimistic-concurrency rule in Section 2.6.

### 2.6. Optimistic Concurrency on Fee-Bill Creation

Creating a fee bill is guarded by optimistic concurrency control against the parent `Assignment`. A create-fee-bill request must carry `expected_assignment_version`, which is the `version` of the target `Assignment` that the client last observed. If `expected_assignment_version` does not equal the assignment's current `version`, the request is rejected with `ERR_STALE_ASSIGNMENT_VERSION` (HTTP 412), and this check is performed before any billing computation.

This guard matters because fee-bill creation itself advances the assignment's `version`. Each create mints a fresh `DRAFT` bill that **supersedes** any prior non-`PAID` bill for the same assignment (the prior bill is voided) and increments the assignment's `version` by 1. Consequently, a client that created or observed a bill and then tries to create another using an `expected_assignment_version` captured before that supersession — or before the assignment's work or billing dimension advanced — is operating on an out-of-date view and is refused. No other endpoint accepts a version field; the OCC contract exists only on fee-bill creation.

### 2.7. Monetary Precision and Rounding

All monetary amounts are stored and computed as integer cents. Two distinct rounding disciplines apply, and each is pinned to a specific place in its calculation:

- **Estimate valuation uses round-half-up.** When depreciating a line item to its actual cash value, the result is rounded half-up to whole cents **per line item, before the lines are summed** — never sum-then-round.
- **Fee-bill amounts use floor (truncation toward zero for non-negative values).** The percent-of-RCV component is floored, and when a catastrophe multiplier applies it is applied to the base and the product is then floored. The order — multiply then floor — is fixed.

Reserve totals, roster counts, and replacement-cost carryovers are whole-cent or integer aggregates with no additional rounding.

### 2.8. The Claim Reserve Ledger and the Roster Invariant

Two running aggregates are maintained by the system as side effects of state transitions rather than being supplied by clients.

A claim's `reserve_consumed_cents` equals the sum of `total_cents` over every fee bill on that claim whose `status` is `SUBMITTED`, `APPROVED`, or `PAID`. Bills in `DRAFT`, `REJECTED`, or `VOID` are excluded. Submitting a bill adds its `total_cents` to the claim's consumed reserve; rejecting or voiding a bill that had been counted subtracts it again. The invariant is that `reserve_consumed_cents` always reconciles to that filtered sum.

A catastrophe event's `roster_filled_count` equals the number of deployments for that event whose `status` is `CONFIRMED` or `ACTIVE`. Confirming a deployment increments it by 1; completing a deployment decrements it by 1; withdrawing a deployment that currently holds a seat (one that was `CONFIRMED` or `ACTIVE`) decrements it by 1 as a compensating adjustment. The invariant is that `roster_filled_count` always equals the count of `CONFIRMED`-or-`ACTIVE` deployments on the event.

### 2.9. Ownership, Segregation of Duties, and Left-to-Right Existence

**Existence resolution.** Any endpoint that references resource ids — whether in the URL path or the request body — resolves those ids left to right, in path-then-body order, and returns the corresponding not-found error the moment an id fails to resolve (for example `ERR_CLAIM_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_INSPECTION_NOT_FOUND`). Each entity has its own not-found code, enumerated in Section 5.

**Ownership.** For the two entity-backed roles, acting on an assignment-scoped resource requires that `X-User-ID` match the `adjuster_id` of the governing `Assignment`. This applies to a `FieldAdjuster` accepting or declining an assignment, starting or completing an inspection, approving an estimate, submitting a report, and submitting a fee bill. A mismatch yields `ERR_NOT_ASSIGNMENT_OWNER` (HTTP 403).

**Segregation of duties.** When a `QAReviewer` renders a decision on a report, the acting reviewer's `X-User-ID` must not equal the authoring adjuster — that is, the `adjuster_id` of the report's parent `Assignment`. A reviewer attempting to QA their own work is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).

### 2.10. Validation Ordering

When several checks could reject the same request, they are evaluated in a fixed priority order so that the returned error is deterministic:

1. **User-context headers** — headers present and role known, else `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`.
2. **Role permission** — the role may perform this operation, else `ERR_INSUFFICIENT_PERMISSIONS`.
3. **Existence** — every referenced id resolves left to right, else the matching `ERR_*_NOT_FOUND`.
4. **Segregation of duties** — on a QA decision, reviewer is not the author, else `ERR_SEGREGATION_OF_DUTIES`.
5. **Ownership** — the acting adjuster owns the assignment-scoped resource, else `ERR_NOT_ASSIGNMENT_OWNER`.
6. **Optimistic concurrency** — on fee-bill creation, `expected_assignment_version` matches, else `ERR_STALE_ASSIGNMENT_VERSION`.
7. **Legal state** — the target resource is in a from-state permitting the transition, else the transition's state-specific conflict error.
8. **License gate** — on assignment accept, the adjuster holds a current license for the loss state, else `ERR_NO_ACTIVE_LICENSE`.
9. **Deployment overlap** — on deployment confirm, the window does not overlap, else `ERR_DEPLOYMENT_WINDOW_OVERLAP`.
10. **Inspection spacing** — on inspection create, the window respects the minimum gap, else `ERR_INSPECTION_SPACING_CONFLICT`.
11. **Report photos** — on report submit, at least one photo, else `ERR_REPORT_NO_PHOTOS`.
12. **Roster capacity** — on deployment confirm, a seat is available, else `ERR_ROSTER_CAPACITY_EXCEEDED`.
13. **Request shape** — body-level field constraints, else `ERR_INVALID_REQUEST`.
14. **Time-entry presence** — on a time-and-expense fee bill, at least one time entry exists, else `ERR_NO_TIME_ENTRIES`.

Two orderings deserve emphasis because they are frequently mis-sequenced. On deployment confirm, the window-overlap check precedes the roster-capacity check, so an overlapping window surfaces as `ERR_DEPLOYMENT_WINDOW_OVERLAP` even when the roster is also full. On assignment accept, the assignment's own state is checked before the cross-entity license gate, so an assignment that is not in the offered state surfaces its state error rather than a licensing error.

## 3. Business Logic & Workflows

### 3.1. Adjuster Onboarding and Multi-State Licensing

A `LicensingAdmin` establishes each adjuster's profile, supplying `full_name`, `email`, `adjuster_type` — one of `INDEPENDENT`, `CAT`, or `STAFF` — and the two-letter `home_state`. A new adjuster's `status` begins as `ACTIVE` and may only ever be `ACTIVE` or `INACTIVE`.

Because catastrophe work crosses state lines, an adjuster carries one license per state they are authorized in. The admin creates each license against a specific adjuster by supplying `adjuster_id`, the two-letter `state_code` the license authorizes, the `license_number`, a `license_type` of either `ALL_LINES` or `PROPERTY`, and the `issued_at` and `expires_at` timestamps. A newly created license enters `PENDING`.

A license moves through its lifecycle under admin control. Activating a `PENDING` license transitions it to `ACTIVE`, but only if the license is genuinely `PENDING` (otherwise `ERR_LICENSE_NOT_PENDING`) and the logical clock is strictly before `expires_at` (otherwise `ERR_LICENSE_EXPIRED`). An `ACTIVE` license may be suspended, moving `ACTIVE → SUSPENDED`, provided it is currently `ACTIVE` (otherwise `ERR_LICENSE_NOT_ACTIVE`). A `SUSPENDED` license may be reinstated, moving `SUSPENDED → ACTIVE`, provided it is currently `SUSPENDED` (otherwise `ERR_LICENSE_NOT_SUSPENDED`) and, again, the clock is strictly before `expires_at` (otherwise `ERR_LICENSE_EXPIRED`). Separately, expiry is automatic: whenever a license in `ACTIVE` or `SUSPENDED` is used while the clock is at or past its `expires_at`, it is treated as `EXPIRED`, which is a terminal state. Activation and reinstatement are the only two admin transitions gated on the expiry boundary; suspension is not.

### 3.2. Catastrophe Events and the Deployment Roster

When a catastrophe strikes, a `LicensingAdmin` opens a catastrophe event by supplying its `name`, classifying its `peril_type` — one of `HURRICANE`, `FLOOD`, `WILDFIRE`, `TORNADO`, `HAIL`, or `WIND` — listing the `affected_states` as an array of two-letter codes, and setting the `roster_capacity`, the maximum number of adjusters who may be concurrently rostered. The event opens in `OPEN` with `roster_filled_count` initialized to 0.

Staffing an event is a roster workflow. The admin first requests a deployment, supplying `adjuster_id`, `cat_event_id`, and a deployment window defined by `start_at` (inclusive) and `end_at` (exclusive, and required to be strictly after `start_at`). A requested deployment begins in `REQUESTED`.

Confirming a deployment moves it `REQUESTED → CONFIRMED` and is where the roster rules bite. The deployment must currently be `REQUESTED` (otherwise `ERR_DEPLOYMENT_NOT_REQUESTED`), and the parent event must be `OPEN` (otherwise `ERR_CAT_EVENT_NOT_OPEN`). Then two guards apply in order. First, the requested window must not overlap any other `CONFIRMED`-or-`ACTIVE` deployment for the **same adjuster**; because windows are half-open, two windows conflict only if they share an interior instant, and windows that merely touch end-to-start are allowed — an overlap is rejected with `ERR_DEPLOYMENT_WINDOW_OVERLAP`. Second, and only after the overlap check passes, the event must have a free seat: the current `roster_filled_count` must be strictly less than `roster_capacity`, else `ERR_ROSTER_CAPACITY_EXCEEDED`. On success the confirmation fills a seat, incrementing the event's `roster_filled_count` by 1.

A `CONFIRMED` deployment is activated when the clock is inside its window: activation moves it `CONFIRMED → ACTIVE` and requires that the deployment be `CONFIRMED` (otherwise `ERR_DEPLOYMENT_NOT_CONFIRMED`) and that the clock satisfy `start_at` at-or-before now and now strictly before `end_at` (otherwise `ERR_DEPLOYMENT_WINDOW_NOT_OPEN`). Completing an `ACTIVE` deployment moves it `ACTIVE → COMPLETED` — requiring it be `ACTIVE`, else `ERR_DEPLOYMENT_NOT_ACTIVE` — and releases its seat by decrementing `roster_filled_count` by 1. At any point while a deployment is `REQUESTED`, `CONFIRMED`, or `ACTIVE` it may be withdrawn to `WITHDRAWN` (otherwise `ERR_DEPLOYMENT_NOT_WITHDRAWABLE`); if the withdrawn deployment had been holding a seat — that is, its prior status was `CONFIRMED` or `ACTIVE` — the withdrawal applies the compensating decrement of `roster_filled_count` by 1, whereas withdrawing a still-`REQUESTED` deployment touches no seat.

An event is closed by the admin, moving it `OPEN → CLOSED`, but only when it is `OPEN` (otherwise `ERR_CAT_EVENT_NOT_OPEN`) and its roster is empty — no deployment for the event remains `CONFIRMED` or `ACTIVE` (otherwise `ERR_ROSTER_NOT_EMPTY`). `CLOSED` is terminal.

### 3.3. Claim Intake and Assignment

A `DeskExaminer` opens each claim, supplying the carrier's `claim_number`, the `policyholder_name`, the two-letter `loss_state` where the loss occurred, the `peril_type` — here drawn from the wider set `HURRICANE`, `FLOOD`, `WILDFIRE`, `TORNADO`, `HAIL`, `WIND`, `FIRE`, or `WATER` — and the `policy_type`, either `RCV` or `ACV`, which will later select the estimate's net-payable variant. A claim may optionally be linked to a catastrophe event through `cat_event_id`; for ordinary daily-claim work this is omitted. A new claim opens in `INTAKE` with `rcv_cents` and `reserve_consumed_cents` both 0.

The examiner then offers the work to an adjuster by creating an assignment that names the `claim_id` and the `adjuster_id`; the system stamps `offered_at` and sets the assignment's two independent dimensions to their initial values, `work_status` = `OFFERED` and `billing_status` = `NOT_BILLED`. Creating the first assignment on an `INTAKE` claim advances that claim `INTAKE → ASSIGNED` as a system side effect.

The offered adjuster responds. Accepting an offer moves the assignment `OFFERED → ACCEPTED`, but only if the assignment is `OFFERED` (otherwise `ERR_ASSIGNMENT_NOT_OFFERED`), the acting `FieldAdjuster` owns it, and the adjuster holds a qualifying license — an `AdjusterLicense` in `ACTIVE` status whose `state_code` equals the claim's `loss_state` and whose `expires_at` is strictly after the current clock (otherwise `ERR_NO_ACTIVE_LICENSE`). The assignment's own offered-state check is evaluated before this license gate. Acceptance also advances the claim: a claim in `ASSIGNED` moves to `IN_PROGRESS`, and likewise a claim in `REOPENED` moves to `IN_PROGRESS`. Declining an offer instead moves the assignment `OFFERED → DECLINED` (again requiring the offered state and ownership); `DECLINED` is terminal for that assignment, and declined assignments are disregarded by the claim-closure accounting described in Section 3.7.

A claim's own dimension is a longer arc: `INTAKE → ASSIGNED → IN_PROGRESS → UNDER_REVIEW → SETTLED → CLOSED`, with a reopen path `CLOSED → REOPENED → IN_PROGRESS`. A `DeskExaminer` reopens a claim, moving it `CLOSED → REOPENED`, only when the claim is `CLOSED` (otherwise `ERR_CLAIM_NOT_CLOSED`); the reopened claim returns to `IN_PROGRESS` as a system effect when an assignment on it is next accepted or its fieldwork resumes. The individual `UNDER_REVIEW`, `SETTLED`, and closure transitions are all system-driven side effects of the report, QA, and payment workflows and are detailed in the sections that follow.

### 3.4. Fieldwork: Inspections and Estimates

Once an assignment is accepted, its adjuster schedules an on-site inspection, supplying the `assignment_id`, the denormalized `claim_id`, and a window of `scheduled_start` and `scheduled_end` (which must be strictly after the start). A new inspection begins in `SCHEDULED`. To prevent double-booking the same property, a spacing rule governs creation: the new `[scheduled_start, scheduled_end)` window must be separated from every other non-terminal inspection **on the same claim** by at least 240 minutes — that is, four hours — of clearance. Concretely, either the new window starts at least 240 minutes after another inspection ends, or the new window ends at least 240 minutes before another begins; anything closer is rejected with `ERR_INSPECTION_SPACING_CONFLICT`.

Starting an inspection moves it to `IN_PROGRESS`. It may be started from either `SCHEDULED` or, after a QA-driven reopen, `REOPENED` (a start from any other state is `ERR_INSPECTION_NOT_SCHEDULED`); the acting adjuster must own the parent assignment. A start out of `SCHEDULED` additionally requires that the parent `Assignment` be in work-status `ACCEPTED` (otherwise `ERR_ASSIGNMENT_NOT_ACCEPTED`), and it carries a cross-entity side effect: the parent assignment advances `ACCEPTED → FIELDWORK`. Completing an in-progress inspection moves it `IN_PROGRESS → COMPLETED`, requiring the `IN_PROGRESS` state (otherwise `ERR_INSPECTION_NOT_IN_PROGRESS`) and assignment ownership.

Against a completed inspection the adjuster builds a Xactimate-style estimate, supplying the `inspection_id`, the `claim_id`, and the `line_items` — a non-empty array of objects, each with a `description`, an integer `rcv_cents` that is at least 0, and a `depreciation_pct` between 0 and 100 inclusive. A new estimate is a `DRAFT`. On creation (and on any recompute of a draft's line items) the system derives four figures. The `rcv_total_cents` is the sum of every line's `rcv_cents`. The `acv_total_cents` is computed by depreciating each line to its actual cash value — the line's `rcv_cents` multiplied by one minus its `depreciation_pct` divided by 100 — rounding that per-line result half-up to whole cents, and then summing the rounded line values (the rounding is per line, before summing). The `recoverable_depreciation_cents` is the `rcv_total_cents` minus the `acv_total_cents`. Finally the `net_payable_cents` is variant by the parent claim's `policy_type`: for an `ACV` policy it equals `acv_total_cents` (the depreciated value only), and for an `RCV` policy it equals `rcv_total_cents` (full replacement cost, with the recoverable depreciation held for later release).

Approving an estimate moves it `DRAFT → APPROVED` and requires that it be `DRAFT` (otherwise `ERR_ESTIMATE_NOT_DRAFT`), that the parent inspection be `COMPLETED` (otherwise `ERR_INSPECTION_NOT_COMPLETED`), and that the acting adjuster own the assignment. Approval writes back to the claim: the claim's `rcv_cents` is set to this estimate's `rcv_total_cents`, which is what later feeds fee-schedule billing. When a claim has more than one approved estimate, its `rcv_cents` reflects the approved estimate with the latest `created_at`; should two approved estimates share the same `created_at`, the one approved most recently — the later `updated_at` — wins, and the resource `id` is never used as a tie-breaker.

### 3.5. Reporting and Quality-Assurance Review

Alongside the estimate, the adjuster prepares a scope-and-photo report against the completed inspection, supplying the `inspection_id`, the denormalized `assignment_id`, a free-text `scope_narrative`, and a `photo_count` (a non-negative integer that defaults to 0 when omitted). A new report is a `DRAFT` with `revision_count` of 0, and its `qa_reviewer_id`, `qa_decision`, and `qa_notes` all remain unset until the first QA decision is rendered.

Submitting a report moves it to `SUBMITTED` and may be done from `DRAFT` on the first pass or from `REVISION_REQUESTED` on a resubmission (a submit from any other state is `ERR_REPORT_NOT_SUBMITTABLE`). Submission is heavily gated: the acting adjuster must own the assignment; the parent inspection must be `COMPLETED` (otherwise `ERR_INSPECTION_NOT_COMPLETED`); an `APPROVED` estimate must exist for that same parent inspection (otherwise `ERR_ESTIMATE_NOT_APPROVED`); and the report's `photo_count` must be at least 1 (otherwise `ERR_REPORT_NO_PHOTOS`). A successful submission carries two forward side effects: the parent assignment advances `FIELDWORK → WORK_COMPLETE`, and the claim advances `IN_PROGRESS → UNDER_REVIEW`.

Review is performed by a `QAReviewer`, who renders a `decision` of either `APPROVED` or `REVISION_REQUESTED` (any other value is `ERR_INVALID_DECISION`) and may attach `qa_notes`. The report must be `SUBMITTED` for a decision to be valid (otherwise `ERR_REPORT_NOT_IN_REVIEW`), and segregation of duties applies: the reviewer's `X-User-ID` must differ from the authoring adjuster (the parent assignment's `adjuster_id`), else `ERR_SEGREGATION_OF_DUTIES`. Either decision records `qa_reviewer_id` = the acting reviewer, sets `qa_decision`, and stores the supplied `qa_notes`.

An **approval** moves the report `SUBMITTED → APPROVED` (terminal) and advances the claim `UNDER_REVIEW → SETTLED`. A **revision request** moves the report `SUBMITTED → REVISION_REQUESTED`, increments `revision_count` by 1, and triggers a three-hop revert cascade: hop one, the parent inspection reverts `COMPLETED → REOPENED`; hop two, caused by that inspection reopening, the parent assignment reverts `WORK_COMPLETE → FIELDWORK`; hop three, caused by the assignment reverting, the claim reverts `UNDER_REVIEW → IN_PROGRESS`. The adjuster then reworks and resubmits — restarting the reopened inspection, re-completing it, and submitting the report again — whereupon the same forward side effects (assignment back to `WORK_COMPLETE`, claim back to `UNDER_REVIEW`) fire once more. This submit/revise loop may cycle any number of times before an eventual approval.

### 3.6. Timekeeping and Fee Billing

Throughout fieldwork the adjuster logs time and expenses. Each time entry names the `assignment_id`, the `work_date`, an `activity` of `INSPECTION`, `ESTIMATING`, `REPORT`, or `TRAVEL`, the billable `hours` (strictly greater than 0, up to two decimals), and an optional `expense_cents` reimbursable amount (a non-negative integer defaulting to 0). Time entries are immutable ledger rows and carry no version.

Billing begins by creating a fee bill, which names the `assignment_id`, the denormalized `claim_id`, the `fee_schedule_id` rate card to apply, the `billing_method` — either `FEE_SCHEDULE` or `TIME_AND_EXPENSE` — and the OCC guard `expected_assignment_version` described in Section 2.6. Creation mints a `DRAFT` bill, supersedes (voids) any prior non-`PAID` bill for the assignment, increments the assignment's `version` by 1, and computes the bill's `subtotal_cents` and `total_cents`. A time-and-expense bill additionally requires that the assignment have at least one logged time entry; creating one against an assignment with no entries is rejected with `ERR_NO_TIME_ENTRIES`.

The two methods compute differently and read different inputs. A **fee-schedule** bill ignores logged time and reads the claim's carried `rcv_cents` together with the named fee schedule's configuration. The schedule's tiers are defined by `tier1_max_rcv_cents` and `tier2_max_rcv_cents`: a claim RCV at or below `tier1_max_rcv_cents` selects the `tier1_flat_fee_cents`; an RCV above tier 1 but at or below `tier2_max_rcv_cents` selects the `tier2_flat_fee_cents`; anything above tier 2 selects the `tier3_flat_fee_cents`. To that flat fee is added a percent-of-RCV component: the schedule's `rcv_pct_bps` (basis points, where 250 means 2.5%) divided by 10000, multiplied by the RCV — but with the RCV first capped at `pct_cap_cents`, so the smaller of the actual RCV and `pct_cap_cents` is used — and the product floored to whole cents. The flat fee plus this floored percent component is the base. If the claim's `peril_type` is a catastrophe peril — one of `HURRICANE`, `FLOOD`, `WILDFIRE`, or `TORNADO` (note that `HAIL`, `WIND`, `FIRE`, and `WATER` are **not** catastrophe perils for this purpose) — the base is scaled by the schedule's `cat_peril_multiplier_bps` (basis points, where 12500 means 1.25×): the base is multiplied by `cat_peril_multiplier_bps`, divided by 10000, and the result floored, in that order. Otherwise the base is used unscaled. That figure is the `subtotal_cents`, and because fee-schedule bills carry no expenses, the `total_cents` equals the `subtotal_cents`.

A **time-and-expense** bill instead ignores the claim RCV and the tiers entirely. Its labor figure is the sum of `hours` across every time entry on the assignment, multiplied by the schedule's `hourly_rate_cents`, with the product floored to whole cents; that labor is the `subtotal_cents`. The `total_cents` is the labor plus the sum of `expense_cents` across those same time entries.

### 3.7. Fee-Bill Lifecycle, Payment, and Claim Closure

A fee bill advances through `DRAFT → SUBMITTED → APPROVED → PAID`, with side branches `SUBMITTED → REJECTED` and `DRAFT`/`SUBMITTED`/`APPROVED → VOID`. Submitting a `DRAFT` bill is the adjuster's act and requires the `DRAFT` state (otherwise `ERR_FEE_BILL_NOT_DRAFT`), assignment ownership, and that the parent assignment be `WORK_COMPLETE` (otherwise `ERR_ASSIGNMENT_NOT_WORK_COMPLETE`). Submission has two side effects: the assignment's billing dimension advances `NOT_BILLED → BILLED`, and the claim's `reserve_consumed_cents` increases by the bill's `total_cents`.

The remaining transitions are the `BillingManager`'s. Approving a `SUBMITTED` bill moves it `SUBMITTED → APPROVED` (otherwise `ERR_FEE_BILL_NOT_SUBMITTED`). Rejecting a `SUBMITTED` bill moves it `SUBMITTED → REJECTED` (same state guard) and compensates the ledger: the assignment's billing dimension reverts `BILLED → NOT_BILLED` and the claim's `reserve_consumed_cents` decreases by the bill's `total_cents`. Voiding a bill is permitted from `DRAFT`, `SUBMITTED`, or `APPROVED` (otherwise `ERR_FEE_BILL_NOT_VOIDABLE`); if the voided bill had already debited the reserve — that is, its prior status was `SUBMITTED` or `APPROVED` — the void applies the same compensation, reverting the assignment to `NOT_BILLED` and subtracting the bill's `total_cents` from `reserve_consumed_cents`, whereas voiding a still-`DRAFT` bill touches neither. `REJECTED` and `VOID` are terminal.

Paying an `APPROVED` bill (otherwise `ERR_FEE_BILL_NOT_APPROVED`) is the settlement act. It moves the bill `APPROVED → PAID` and creates a `Payment` recording the `fee_bill_id`, an `amount_cents` equal to the bill's `total_cents` at that moment, the `method` of either `ACH` or `CHECK`, and a `paid_at` stamped from the logical clock. Payment then cascades: hop one, the assignment's billing dimension advances `BILLED → PAID`; hop two, caused by that assignment becoming paid, if the claim is `SETTLED` and every one of its non-declined assignments is now in billing status `PAID`, the claim advances `SETTLED → CLOSED`. Claim closure therefore requires both that QA has settled the claim and that all billable work on it has been paid in full; declined assignments are excluded from that all-paid test.

## 4. Endpoint Definitions

All endpoints share the response envelope of Section 2.2. Creation endpoints return HTTP 201 with the newly created resource; state-transition and other mutation endpoints return HTTP 200 with the updated resource; reads return HTTP 200. Authorization failures, missing resources, illegal states, and rule violations return the errors of Section 5.

| Method | Path | Description | Authorized Role(s) |
|--------|------|-------------|--------------------|
| POST | `/_clock/set_current_utc` | Set the server logical clock | DeskExaminer, LicensingAdmin, BillingManager |
| POST | `/adjusters` | Create an adjuster profile | LicensingAdmin |
| GET | `/adjusters` | List adjusters | All roles |
| GET | `/adjusters/{id}` | Get an adjuster | All roles |
| POST | `/licenses` | Create a license (starts PENDING) | LicensingAdmin |
| GET | `/licenses` | List licenses | All roles |
| GET | `/licenses/{id}` | Get a license | All roles |
| POST | `/licenses/{id}/activate` | Activate a PENDING license | LicensingAdmin |
| POST | `/licenses/{id}/suspend` | Suspend an ACTIVE license | LicensingAdmin |
| POST | `/licenses/{id}/reinstate` | Reinstate a SUSPENDED license | LicensingAdmin |
| POST | `/cat-events` | Create a catastrophe event | LicensingAdmin |
| GET | `/cat-events` | List cat events | All roles |
| GET | `/cat-events/{id}` | Get a cat event | All roles |
| POST | `/cat-events/{id}/close` | Close a cat event (roster must be empty) | LicensingAdmin |
| POST | `/deployments` | Request a deployment | LicensingAdmin |
| GET | `/deployments` | List deployments | All roles |
| GET | `/deployments/{id}` | Get a deployment | All roles |
| POST | `/deployments/{id}/confirm` | Confirm a deployment (overlap + capacity) | LicensingAdmin |
| POST | `/deployments/{id}/activate` | Activate a confirmed deployment | LicensingAdmin |
| POST | `/deployments/{id}/complete` | Complete an active deployment | LicensingAdmin |
| POST | `/deployments/{id}/withdraw` | Withdraw a deployment | LicensingAdmin |
| POST | `/claims` | Create a claim (INTAKE) | DeskExaminer |
| GET | `/claims` | List claims | All roles |
| GET | `/claims/{id}` | Get a claim | All roles |
| POST | `/claims/{id}/reopen` | Reopen a CLOSED claim | DeskExaminer |
| POST | `/assignments` | Offer an assignment | DeskExaminer |
| GET | `/assignments` | List assignments | All roles |
| GET | `/assignments/{id}` | Get an assignment | All roles |
| POST | `/assignments/{id}/accept` | Accept an offered assignment | FieldAdjuster |
| POST | `/assignments/{id}/decline` | Decline an offered assignment | FieldAdjuster |
| POST | `/inspections` | Schedule an inspection | FieldAdjuster |
| GET | `/inspections` | List inspections | All roles |
| GET | `/inspections/{id}` | Get an inspection | All roles |
| POST | `/inspections/{id}/start` | Start (or restart) an inspection | FieldAdjuster |
| POST | `/inspections/{id}/complete` | Complete an inspection | FieldAdjuster |
| POST | `/estimates` | Create an estimate (DRAFT) | FieldAdjuster |
| GET | `/estimates` | List estimates | All roles |
| GET | `/estimates/{id}` | Get an estimate | All roles |
| POST | `/estimates/{id}/approve` | Approve a DRAFT estimate | FieldAdjuster |
| POST | `/reports` | Create a report (DRAFT) | FieldAdjuster |
| GET | `/reports` | List reports | All roles |
| GET | `/reports/{id}` | Get a report | All roles |
| POST | `/reports/{id}/submit` | Submit (or resubmit) a report | FieldAdjuster |
| POST | `/reports/{id}/qa-decision` | QA approve or request revision | QAReviewer |
| POST | `/time-entries` | Log a time/expense entry | FieldAdjuster |
| GET | `/time-entries` | List time entries | All roles |
| GET | `/time-entries/{id}` | Get a time entry | All roles |
| POST | `/fee-schedules` | Create a fee schedule | BillingManager |
| GET | `/fee-schedules` | List fee schedules | All roles |
| GET | `/fee-schedules/{id}` | Get a fee schedule | All roles |
| POST | `/fee-bills` | Create a fee bill (DRAFT; supersedes prior; OCC) | FieldAdjuster |
| GET | `/fee-bills` | List fee bills | All roles |
| GET | `/fee-bills/{id}` | Get a fee bill | All roles |
| POST | `/fee-bills/{id}/submit` | Submit a DRAFT fee bill | FieldAdjuster |
| POST | `/fee-bills/{id}/approve` | Approve a submitted fee bill | BillingManager |
| POST | `/fee-bills/{id}/reject` | Reject a submitted fee bill | BillingManager |
| POST | `/fee-bills/{id}/void` | Void a fee bill | BillingManager |
| POST | `/fee-bills/{id}/pay` | Pay an approved fee bill | BillingManager |
| GET | `/payments` | List payments | All roles |
| GET | `/payments/{id}` | Get a payment | All roles |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|----------|------------------|
| ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER | 400 |
| ERR_INSUFFICIENT_PERMISSIONS | 403 |
| ERR_NOT_ASSIGNMENT_OWNER | 403 |
| ERR_SEGREGATION_OF_DUTIES | 403 |
| ERR_ADJUSTER_NOT_FOUND | 404 |
| ERR_LICENSE_NOT_FOUND | 404 |
| ERR_CAT_EVENT_NOT_FOUND | 404 |
| ERR_DEPLOYMENT_NOT_FOUND | 404 |
| ERR_CLAIM_NOT_FOUND | 404 |
| ERR_ASSIGNMENT_NOT_FOUND | 404 |
| ERR_INSPECTION_NOT_FOUND | 404 |
| ERR_ESTIMATE_NOT_FOUND | 404 |
| ERR_REPORT_NOT_FOUND | 404 |
| ERR_TIME_ENTRY_NOT_FOUND | 404 |
| ERR_FEE_SCHEDULE_NOT_FOUND | 404 |
| ERR_FEE_BILL_NOT_FOUND | 404 |
| ERR_PAYMENT_NOT_FOUND | 404 |
| ERR_INVALID_REQUEST | 400 |
| ERR_STALE_ASSIGNMENT_VERSION | 412 |
| ERR_LICENSE_NOT_PENDING | 409 |
| ERR_LICENSE_NOT_ACTIVE | 409 |
| ERR_LICENSE_NOT_SUSPENDED | 409 |
| ERR_LICENSE_EXPIRED | 409 |
| ERR_NO_ACTIVE_LICENSE | 422 |
| ERR_CAT_EVENT_NOT_OPEN | 409 |
| ERR_ROSTER_NOT_EMPTY | 409 |
| ERR_DEPLOYMENT_NOT_REQUESTED | 409 |
| ERR_DEPLOYMENT_NOT_CONFIRMED | 409 |
| ERR_DEPLOYMENT_NOT_ACTIVE | 409 |
| ERR_DEPLOYMENT_NOT_WITHDRAWABLE | 409 |
| ERR_DEPLOYMENT_WINDOW_NOT_OPEN | 409 |
| ERR_DEPLOYMENT_WINDOW_OVERLAP | 409 |
| ERR_ROSTER_CAPACITY_EXCEEDED | 409 |
| ERR_INSPECTION_SPACING_CONFLICT | 409 |
| ERR_INSPECTION_NOT_SCHEDULED | 409 |
| ERR_INSPECTION_NOT_IN_PROGRESS | 409 |
| ERR_INSPECTION_NOT_COMPLETED | 409 |
| ERR_ASSIGNMENT_NOT_OFFERED | 409 |
| ERR_ASSIGNMENT_NOT_ACCEPTED | 409 |
| ERR_ASSIGNMENT_NOT_WORK_COMPLETE | 409 |
| ERR_ESTIMATE_NOT_DRAFT | 409 |
| ERR_ESTIMATE_NOT_APPROVED | 409 |
| ERR_REPORT_NOT_SUBMITTABLE | 409 |
| ERR_REPORT_NOT_IN_REVIEW | 409 |
| ERR_REPORT_NO_PHOTOS | 422 |
| ERR_INVALID_DECISION | 400 |
| ERR_NO_TIME_ENTRIES | 422 |
| ERR_FEE_BILL_NOT_DRAFT | 409 |
| ERR_FEE_BILL_NOT_SUBMITTED | 409 |
| ERR_FEE_BILL_NOT_APPROVED | 409 |
| ERR_FEE_BILL_NOT_VOIDABLE | 409 |
| ERR_CLAIM_NOT_CLOSED | 409 |
</content>
</invoke>
