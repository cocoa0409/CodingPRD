# Construction Change Orders API — Product Requirements Document

## 1. Introduction

Commercial construction projects are governed by a dense web of paper instruments: the schedule of values that breaks a contract into billable line items, the AIA G702/G703 pay application that contractors submit each month, the change order log that revises the contract sum, the request-for-information and submittal logs that keep the design intent current, and the lien-waiver and retention-release machinery that settles money against legal exclusivity. This API replaces those instruments with a single ledger-reconciliation service. It holds the authoritative numbers — what was billed, what was completed, how much retainage is being withheld, what the contract sum is after every approved change — and it enforces the sequencing and segregation-of-duties rules that make those numbers trustworthy.

The system is organized around a flat family of peer resources that all hang off a parent **Project**. Schedule-of-values lines, pay applications, change orders, RFIs, submittals, subcontractor commitments, lien waivers, punch-list items, inspection windows, and retention releases each carry an explicit reference to the project they belong to; there is no deep URL nesting. The hard problems live in the reconciliation: a certified pay application must write its billed work and withheld retainage back into the schedule of values; an approved change order must edit those same lines and recompute the contract sum; a retention release must draw retainage down across lines in a fixed order. Because several of these operations advance a shared project version, the API uses optimistic concurrency control to reject writes that were composed against a stale view of the ledger.

Three parties collaborate under a strict separation of responsibilities. The Owner awards and closes the project and holds the purse strings; the Contractor builds the schedule of values and bills against it; the Architect certifies that the billing reflects work actually in place. No single actor may both submit and certify the same pay application — the cornerstone control of construction payment.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, response contracts, and cross-cutting financial principles that apply across every endpoint.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory HTTP headers: `X-User-ID`, which identifies the acting operator, and `X-User-Role`, which declares the capacity in which they are acting. The system recognizes exactly three roles, spelled precisely as `Owner`, `Contractor`, and `Architect`. If either header is absent, or if `X-User-Role` is not one of these three known roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are valid but the role is not permitted to invoke the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

All three roles carry an **opaque** identity. When `X-User-Role` is `Owner`, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity; the server records it where a transition writes it (for example, as `approved_by_user_id` on a `ChangeOrder` or `RetentionRelease`, or as `owner_user_id` on a `Project` at creation) but never compares it to any entity's `id`. When `X-User-Role` is `Contractor`, `X-User-ID` is likewise an opaque operator identifier; the server may record it (for example, as `submitted_by_user_id` on a `PayApplication` or `ChangeOrder`) but does not treat it as an entity id. When `X-User-Role` is `Architect`, `X-User-ID` is again an opaque operator identifier; the server records it (for example, as `certified_by_user_id` on a `PayApplication`) without resolving it to any stored record. The one place an opaque id is compared against another opaque id is the segregation-of-duties control described in §2.7, where the certifying or rejecting architect's `X-User-ID` is checked against the `submitted_by_user_id` that was captured when the application was submitted.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps how many items a single response returns; when omitted it defaults to 10, and it is constrained to a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip from the start of the result set and defaults to 0.

Unless a specific endpoint states otherwise, every list endpoint returns its resources sorted by their creation timestamp (`created_at`) in ascending order. Each list response carries the pagination bookkeeping in the `meta` object, namely `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Resource Identity, Timestamps, and Versioning

Most resources in this system are versioned, audit-bearing records. Every `Project`, `SovLine`, `ChangeOrder`, `PayApplication`, `SubcontractorCommitment`, `Rfi`, `Submittal`, `LienWaiver`, `PunchListItem`, `InspectionWindow`, and `RetentionRelease` carries four system-managed fields: an `id` that is a server-minted UUID with no type prefix; a `created_at` timestamp recorded as an ISO 8601 UTC string with three fractional digits at the moment the record is first created; an `updated_at` timestamp of the same format refreshed on every subsequent mutation; and an integer `version` that begins at 1 and increments by one on every mutation of that record. The `version` field underpins the optimistic concurrency control described in §2.6.

The single exception is the **PayAppLine**, the G703 billing detail. A `PayAppLine` is an immutable billing fact: once created it is not edited in place, so it carries only an `id` (a server-minted UUID) and a `created_at` timestamp. It has neither an `updated_at` field nor a `version` field.

### 2.5. Derived-Field Reconciliation and Cascade Discipline

Four numbers on the `Project` are never written directly by a client; they are **computed** and re-derived whenever an upstream event changes their inputs. The `revised_contract_sum_cents` is the original contract sum plus the net effect of every approved change order. The `total_completed_and_stored_cents` is the project-wide roll-up of completed-and-stored value drawn from the schedule of values as of the most recently certified pay application. The `retainage_held_cents` is the project-wide roll-up of retainage currently withheld across schedule-of-values lines, net of any retention released. The fourth, `version`, is the optimistic-concurrency counter.

These derivations cascade. Approving a change order edits schedule-of-values lines, which forces the contract-sum recomputation; certifying a pay application writes billing and retainage back onto schedule-of-values lines, which forces the project's completed-and-stored and retainage-held roll-ups to be recomputed; approving a retention release draws retainage down across lines, which forces the retainage-held roll-up to be recomputed. Each of these three operations also increments `Project.version` by one and refreshes the project's `updated_at`. The corresponding line-level fields on a `SovLine` — `work_completed_to_date_cents`, `materials_stored_cents`, and `retainage_withheld_to_date_cents` — are likewise computed: they are zero on a freshly created line and only move when a pay application is certified or a retention release is approved. The exact formulas and orderings appear in §3.

### 2.6. Optimistic Concurrency Control on Supersede-on-Create

Two creation endpoints are guarded by optimistic concurrency control because the resource they create is composed against a snapshot of the project ledger. Creating a pay application requires an `expected_project_version` field in the request body carrying the `Project.version` the client last observed. If that value does not equal the project's current `version` — because a change-order approval, a prior certification, or a retention-release approval has advanced the project since the client read it — the create is rejected with `ERR_STALE_PROJECT_VERSION` (HTTP 412), because the schedule-of-values baseline this draft would supersede is no longer the one the client saw. Creating a retention release likewise requires an `expected_project_version` field carrying the client's last observed `Project.version`; if a certification or another approved release has since changed the held retainage and bumped the project's `version`, the create is rejected with the same `ERR_STALE_PROJECT_VERSION` (HTTP 412) rather than sizing a drawdown against an out-of-date balance. In both cases the `expected_project_version` is a guard value only and is not persisted on the created resource.

These two create endpoints are the only endpoints that take a project-version guard. The change-order approval and the retention-release approval transitions also require an `expected_project_version` in their bodies — covered with their workflows in §3 — but no other endpoint takes a version field, and a mismatch is never inferred for an endpoint that does not declare one.

### 2.7. Segregation of Duties

The defining control of construction payment is that the party who bills cannot be the party who certifies. When a pay application is submitted, the submitter's opaque `X-User-ID` is captured as `submitted_by_user_id`. When the application is later certified or rejected by an architect, the architect's `X-User-ID` must differ from that captured `submitted_by_user_id`; if they are equal, the operation is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 409). This single user-identity comparison is the only place opaque identifiers are compared in the whole system.

### 2.8. Resource Existence and Cross-Project Referential Integrity

Every endpoint that names a resource — whether in the URL path or as a foreign key in the request body, such as `project_id`, `sov_line_id`, or `pay_app_id` — must resolve that reference to a real record. References are validated left to right in the order they appear; the first one that does not resolve yields `ERR_NOT_FOUND` (HTTP 404) before any later reference or business rule is evaluated. Beyond mere existence, certain body foreign keys must point into the same project as the parent resource. When a pay-app line is created, the schedule-of-values line named by `sov_line_id` must belong to the same project as the pay application named by `pay_app_id`; when a lien waiver is created, the pay application named by `pay_app_id` must belong to the project named by the waiver's own `project_id`. A foreign key that resolves to a record in a different project is rejected with `ERR_CROSS_PROJECT_REFERENCE` (HTTP 422).

### 2.9. Monetary Precision and Rounding

All money is carried as integer cents; there are no fractional-cent fields. Where a calculation multiplies a retainage fraction by a billed amount, the result is rounded to the nearest whole cent using the round-half-up convention — exactly halfway cases round up. The rounding discipline for the G702 line-5 retainage total is **pinned**: retainage is rounded to a whole cent per line first, and only then are the per-line results summed to form the application total. The system rounds each line, then sums; it never sums the raw products and rounds once at the end. Contract-sum arithmetic, the retainage-release waterfall, and the commitment-invoice sweep are pure integer-cent operations with no rounding.

### 2.10. Validation Ordering

When several checks could fail on a single request, they are evaluated in a fixed priority order so that the returned `error_id` is deterministic. Authentication is checked first (`ERR_UNAUTHENTICATED`), then role authorization (`ERR_FORBIDDEN_ROLE`), then existence of all referenced resources (`ERR_NOT_FOUND`), then cross-project referential integrity for the two endpoints that carry body foreign keys (`ERR_CROSS_PROJECT_REFERENCE`). Only after those four gates does the system evaluate state-machine legality (`ERR_INVALID_STATE`), followed by the segregation-of-duties control (`ERR_SEGREGATION_OF_DUTIES`), then the temporal sequencing and overlap rules in this priority — pay-application sequencing (`ERR_NONSEQUENTIAL_APPLICATION`), pay-application billing-window overlap (`ERR_BILLING_PERIOD_OVERLAP`), and inspection-buffer conflict (`ERR_INSPECTION_BUFFER_CONFLICT`) — then the duplicate-item-number check (`ERR_DUPLICATE_ITEM_NO`), the change-order balance check (`ERR_LINE_EDITS_UNBALANCED`), the overbilling check (`ERR_OVERBILLING`), the release-exceeds-held check (`ERR_RELEASE_EXCEEDS_HELD`), the lien-waiver field-match check (`ERR_WAIVER_MISMATCH`), the pay-application-certified check for waivers (`ERR_PAYAPP_NOT_CERTIFIED`), and the stale-version guard (`ERR_STALE_PROJECT_VERSION`). Generic field-shape validation — required fields present, enums in range, integer and sign constraints — carries the lowest priority and surfaces as `ERR_INVALID_REQUEST` (HTTP 422) when no higher-priority rule has already fired. Field-shape failures of this kind include a non-positive `scheduled_value_cents`, a `default_retainage_pct` outside its permitted band, a negative amount, or a `scheduled_end` that is not strictly after `scheduled_start`.

## 3. Business Logic & Workflows

### 3.1. Standing Up a Project and Its Schedule of Values

An Owner stands up the engagement by creating a **Project**, supplying a non-empty `name`, the `owner_user_id` of the owner of record (an opaque operator id retained for audit only), the baseline `original_contract_sum_cents` at award (which may not be negative), and optionally a `default_retainage_pct`. The retainage default is the fraction of completed work withheld until release; it must lie between 0 and 0.20 inclusive and, when not supplied, is taken to be 0.10. A new project opens with its `status` field set to `ACTIVE` and `version` 1. At creation its `revised_contract_sum_cents` equals the `original_contract_sum_cents`, and its three other derived ledger figures — `total_completed_and_stored_cents`, `retainage_held_cents`, and the line roll-ups behind them — all start at zero.

The Contractor then builds out the **schedule of values** one line at a time. Each `SovLine` create carries the parent `project_id`, an `item_no` (the G703 column-A line number), a `description` of the work (G703 column B), and a `scheduled_value_cents` (G703 column C) that must be strictly greater than zero. The `item_no` must be unique among the active lines of the project; a collision is rejected with `ERR_DUPLICATE_ITEM_NO` (HTTP 409). At creation the line copies its `retainage_pct` from the project's `default_retainage_pct`, opens in `ACTIVE` status, and starts with `work_completed_to_date_cents`, `materials_stored_cents`, and `retainage_withheld_to_date_cents` all at zero. A line may later carry `DELETED` status; the invariant the system maintains is that the sum of `scheduled_value_cents` across the non-deleted lines equals the project's `revised_contract_sum_cents`.

### 3.2. The Change-Order Log and Contract-Sum Revision

Change orders are how the contract sum moves after award. A Contractor drafts a **ChangeOrder** against a `project_id` with a `co_number` unique within the project, a net `change_order_amount_cents` (negative for a deductive change order), and a `line_edits` array describing how the schedule of values is to be edited. Each entry in `line_edits` carries an `action` of either `ADD` or `ADJUST`, an `item_no`, an optional `description`, a `scheduled_value_delta_cents`, and an optional `retainage_pct` which, when supplied, must lie between 0 and 0.20 inclusive — the same band as the project's `default_retainage_pct` — with an out-of-band value rejected as a field-shape failure (`ERR_INVALID_REQUEST`, HTTP 422). The change order opens in `DRAFT`.

When the Contractor submits the draft, it advances `DRAFT → SUBMITTED` only if it is currently `DRAFT` and its parent project is `ACTIVE`; otherwise the attempt is rejected with `ERR_INVALID_STATE` (HTTP 409). Submission records the submitting operator's opaque id as `submitted_by_user_id`.

Approval is the Owner's act and the heaviest cascade in the system. An owner approving a submitted change order must satisfy several preconditions: the change order is in `SUBMITTED` state and its parent project is still `ACTIVE` (else `ERR_INVALID_STATE`); the request body carries an `expected_project_version` equal to the project's current `version` (else `ERR_STALE_PROJECT_VERSION`, HTTP 412); every `ADJUST` edit names an existing `ACTIVE` schedule-of-values line in this project while every `ADD` edit's `item_no` is not already in use by an `ACTIVE` line (else `ERR_DUPLICATE_ITEM_NO`, HTTP 409); and the sum of `scheduled_value_delta_cents` across the edits exactly equals the change order's `change_order_amount_cents` (else `ERR_LINE_EDITS_UNBALANCED`, HTTP 422). When all hold, the change order moves `SUBMITTED → APPROVED` and records the approving operator's opaque id as `approved_by_user_id`. The line edits are then applied: each `ADD` creates a new `ACTIVE` `SovLine` whose scheduled value is the edit's `scheduled_value_delta_cents`, whose `description` is the edit's `description` (or the empty string when the edit omits it), and whose `retainage_pct` defaults to the project's `default_retainage_pct` unless the edit overrides it; each `ADJUST` adds the edit's `scheduled_value_delta_cents` to the named line's `scheduled_value_cents`. A deductive edit reduces a line's scheduled value, which must remain strictly greater than zero; an `ADJUST` that would drop the line's `scheduled_value_cents` to zero or below is rejected with `ERR_INVALID_REQUEST` (HTTP 422). After the lines settle, the project's `revised_contract_sum_cents` is recomputed as the `original_contract_sum_cents` plus the sum of `change_order_amount_cents` over every change order on the project now in `APPROVED` status, and `Project.version` is incremented by one. Rejecting a submitted change order is the alternative branch: an owner may move it `SUBMITTED → REJECTED` whenever it is `SUBMITTED`, and this performs no schedule-of-values or project mutation whatsoever.

### 3.3. Pay Applications: Drafting and Billing Lines (G703)

The monthly billing cycle begins when a Contractor opens a **PayApplication** against a `project_id`. The create body carries an `application_number`, a `period_from` and `period_to` defining the billing window, and the `expected_project_version` OCC guard described in §2.6. The `application_number` must be exactly one greater than the highest `application_number` among the project's pay applications that are not `REJECTED` — or 1 if there are none — and the `period_to` must be strictly later than `period_from` and strictly later than the `period_to` of the prior non-rejected application; any violation of this sequencing is `ERR_NONSEQUENTIAL_APPLICATION` (HTTP 422). Separately, the billing window is the half-open interval running from `period_from` up to but not including `period_to`, and it must not overlap the window of any non-rejected application on the same project. Two such intervals overlap when the first starts before the second ends and the second starts before the first ends; an exact touch where a new application's `period_from` equals a prior application's `period_to` is adjacency, not overlap, and is permitted. An overlapping window is rejected with `ERR_BILLING_PERIOD_OVERLAP` (HTTP 409). A new application opens in `DRAFT` and, as a create against the project ledger, is subject to the `expected_project_version` stale-version guard before anything else about it is persisted.

Into a draft application the Contractor adds **PayAppLine** billing details, one per schedule-of-values line being billed; the line-create operation itself does not gate on the parent application's status, so it neither verifies nor requires that the pay application is still `DRAFT`. A pay-app line create carries the `pay_app_id` of the draft, the `sov_line_id` of the line being billed, a `work_completed_this_period_cents` (the G703 column-E increment, which may not be negative), and an optional `materials_stored_cents` (G703 column F, defaulting to zero, which may not be negative). At creation the line snapshots `work_completed_previous_cents` from the linked `SovLine.work_completed_to_date_cents` as of the most recently certified prior application (zero if none) — this is G703 column D. The system then computes the line's `line_retainage_cents`: it applies the linked schedule-of-values line's `retainage_pct` to the sum of `work_completed_previous_cents`, `work_completed_this_period_cents`, and `materials_stored_cents`, and rounds that product to a whole cent half-up. Retainage is taken on the full cumulative billed amount: even a line that bills only stored materials with no period work still includes its previously billed work in the base on which retainage is computed.

### 3.4. Pay Applications: Submission, Certification, and the Ledger Write-Back

When the Contractor submits a pay application it advances `DRAFT → SUBMITTED`, permitted only when it is `DRAFT`, at least one pay-app line exists for it, and no line overbills — that is, for every line, the sum of `work_completed_previous_cents`, `work_completed_this_period_cents`, and `materials_stored_cents` is at most the linked schedule-of-values line's `scheduled_value_cents`. A line that exceeds its scheduled value is rejected with `ERR_OVERBILLING` (HTTP 422); a wrong-state submit is `ERR_INVALID_STATE`. Submission records the submitting operator as `submitted_by_user_id` and computes the three G702 header totals. The `total_completed_and_stored_cents` (G702 line 4) is the sum over the application's lines of `work_completed_previous_cents` plus `work_completed_this_period_cents` plus `materials_stored_cents`. The `total_retainage_cents` (G702 line 5) is the sum over the lines of `line_retainage_cents`, computed by rounding each line's retainage to a whole cent first and then summing the rounded per-line figures. The `current_payment_due_cents` (G702 line 6 net of line 8) is `total_completed_and_stored_cents` minus `total_retainage_cents` minus the prior-certificates draw, where the prior-certificates draw is the sum of `current_payment_due_cents` over the project's already-certified applications. For the project's first certified application that prior-certificates draw is zero, so the payment due equals completed-and-stored less retainage; for a subsequent application it subtracts the running total of previously certified payment-due amounts, the chronological less-previous-certificates draw.

Certification is the Architect's act and carries the ledger write-back. An architect certifying a submitted application must satisfy three preconditions: the application is `SUBMITTED` (else `ERR_INVALID_STATE`); the certifying `X-User-ID` differs from the application's `submitted_by_user_id` (else `ERR_SEGREGATION_OF_DUTIES`, HTTP 409); and no RFI on the project is `OPEN` with its `ball_in_court` resting on `ARCHITECT` — the architect must clear its own court before certifying, and an open architect-court RFI blocks certification with `ERR_INVALID_STATE`. On success the application moves `SUBMITTED → CERTIFIED`, records the certifying operator as `certified_by_user_id`, and writes each pay-app line back onto its schedule-of-values line: the line's `work_completed_to_date_cents` becomes `work_completed_previous_cents` plus `work_completed_this_period_cents`; its `materials_stored_cents` becomes the pay-app line's `materials_stored_cents`; and its `retainage_withheld_to_date_cents` is increased by the pay-app line's `line_retainage_cents`. With the schedule of values updated, the project's `total_completed_and_stored_cents` and `retainage_held_cents` are recomputed from its lines, and `Project.version` is incremented by one. Rejection is the alternative architect branch: an architect may move a submitted application `SUBMITTED → REJECTED` provided it is `SUBMITTED` and the rejecting `X-User-ID` differs from `submitted_by_user_id` (segregation of duties applies to rejection as well, with the same `ERR_SEGREGATION_OF_DUTIES`). A rejection performs no schedule-of-values or project ledger mutation, and the `application_number` it consumed is freed for reuse, because sequencing counts only non-rejected applications.

### 3.5. RFIs and Submittals: Keeping the Design Current

A Contractor opens a **request for information** against a `project_id` with a `subject` and a `question`. A new RFI is `OPEN` with `ball_in_court` set to `ARCHITECT`, meaning the design team owes the next move. An architect answers an open RFI by supplying an `answer`; this advances it `OPEN → ANSWERED`, sets `ball_in_court` to `CONTRACTOR`, and stores the answer text. A contractor then closes an answered RFI, moving it `ANSWERED → CLOSED`. Either transition from a wrong state is `ERR_INVALID_STATE`. The reason RFIs matter beyond their own log is the certification gate in §3.4: an `OPEN` RFI whose `ball_in_court` is `ARCHITECT` blocks pay-application certification on its project.

The **submittal** log tracks shop-drawing and product approvals. A Contractor logs a submittal against a `project_id` with a `spec_section` (the CSI section, e.g. "03 30 00") and a `title`; it opens `PENDING` with `revision` at 0. An architect reviews a pending submittal by supplying a `decision`, and the resulting state is driven entirely by that decision: a `decision` of `APPROVED` moves it `PENDING → APPROVED`, a `decision` of `APPROVED_AS_NOTED` moves it `PENDING → APPROVED_AS_NOTED`, and a `decision` of `REVISE_AND_RESUBMIT` moves it `PENDING → REVISE_AND_RESUBMIT`. Review is only legal from `PENDING`; otherwise `ERR_INVALID_STATE`. A submittal in `REVISE_AND_RESUBMIT` is sent back by the Contractor, who resubmits it; this advances `REVISE_AND_RESUBMIT → PENDING` and increments `revision` by one, the cyclic revision loop that lets a submittal cycle through review as many times as the design requires. Finally, an architect closes a submittal that an architect has approved: from either `APPROVED` or `APPROVED_AS_NOTED` the submittal moves to `CLOSED`. A close attempted from any other state is `ERR_INVALID_STATE`.

### 3.6. Subcontractor Commitments, Lien Waivers, and the Invoice Sweep

A Contractor records a **subcontractor commitment** against a `project_id`, naming the `subcontractor_name` and a `committed_amount_cents` that must be strictly greater than zero. The commitment opens `OPEN` with `invoiced_to_date_cents` at zero; that invoiced figure is computed and accumulates through lien-waiver activity, and it never exceeds `committed_amount_cents`. A commitment may later be closed by the Contractor, moving `OPEN → CLOSED`, but only once it is fully invoiced — that is, only when `invoiced_to_date_cents` equals `committed_amount_cents`; a close attempted on a not-fully-invoiced or non-open commitment is `ERR_INVALID_STATE`.

A **lien waiver** ties a payment to a release of lien rights. A Contractor records a waiver carrying a `project_id`, the `pay_app_id` of the application whose payment it corresponds to, a `waiver_type` of `CONDITIONAL_PROGRESS`, `UNCONDITIONAL_PROGRESS`, `CONDITIONAL_FINAL`, or `UNCONDITIONAL_FINAL`, a `through_date`, and an `amount_cents` that may not be negative. The linked pay application must be `CERTIFIED`, or the create is rejected with `ERR_PAYAPP_NOT_CERTIFIED` (HTTP 409). The waiver's `amount_cents` must equal the linked application's `current_payment_due_cents` and its `through_date` must equal that application's `period_to`; any mismatch is `ERR_WAIVER_MISMATCH` (HTTP 422). A new waiver opens in `PENDING`.

A pending waiver is made effective when the Contractor notarizes it, advancing `PENDING → EFFECTIVE`. For an unconditional waiver — one whose `waiver_type` is `UNCONDITIONAL_PROGRESS` or `UNCONDITIONAL_FINAL` — notarization is permitted only when the payment it represents has been made, modeled here as the existence of at least one certified pay application on the project whose `current_payment_due_cents` equals this waiver's `amount_cents`; absent such an application the notarize is rejected with `ERR_INVALID_STATE`. Making an unconditional waiver effective also runs the **commitment-invoice sweep**: the system credits exactly one subcontractor commitment, choosing among the project's `OPEN` commitments that still have remaining balance — those whose `invoiced_to_date_cents` is less than their `committed_amount_cents` — the one with the largest remaining balance (`committed_amount_cents` minus `invoiced_to_date_cents`), breaking ties toward the earliest `created_at`. The credit applied to the chosen commitment is the smaller of the waiver's `amount_cents` and that commitment's remaining balance, and it is added to its `invoiced_to_date_cents`. If no commitment is eligible, no commitment is credited and the waiver still becomes `EFFECTIVE`. A conditional waiver — `CONDITIONAL_PROGRESS` or `CONDITIONAL_FINAL` — moves no invoiced ledger at all on notarization; the sweep applies only to unconditional waivers. Alternatively an Owner may void a pending waiver, moving `PENDING → VOID`; a void or notarize from any non-pending state is `ERR_INVALID_STATE`.

### 3.7. Punch List, Inspections, and Project Close-Out

Near the end of the work the Architect catalogs deficiencies as **punch-list items**, each created against a `project_id` with a `location`, a `description`, and an optional `severity` of `MINOR` or `MAJOR` that defaults to `MINOR`. A new item is `OPEN`. The Contractor marks an item ready for review — legal from either `OPEN` or `REOPENED`, advancing the item to `READY_FOR_REVIEW`. The Architect then either verifies it, moving `READY_FOR_REVIEW → VERIFIED`, or reopens it. A reopen is legal from either `READY_FOR_REVIEW` or `VERIFIED` and lands the item in `REOPENED`, forming the cyclic loop `READY_FOR_REVIEW → REOPENED → READY_FOR_REVIEW`. Reopening an item that had reached `VERIFIED` does not revert a project that has already been marked substantially complete; substantial completion is sticky. Any of these transitions attempted from an ineligible state is `ERR_INVALID_STATE`.

A Contractor books an **inspection window** on a `project_id` with an `inspector_name`, a `scheduled_start`, a `scheduled_end` that must be strictly after the start, and an optional `buffer_minutes` clearance that defaults to 30 and may not be negative. The slot is the closed interval running from `scheduled_start` through `scheduled_end` inclusive. A booking must clear every non-cancelled inspection window on the same project by at least its `buffer_minutes`: two slots conflict when the gap between their closed intervals is strictly less than `buffer_minutes`, so a back-to-back booking with a zero gap is a conflict and is rejected with `ERR_INSPECTION_BUFFER_CONFLICT` (HTTP 409). This is deliberately stricter than the pay-application window rule, where exact adjacency is allowed. A new window is `BOOKED`. An architect may mark a booked window `COMPLETED`, or a contractor may cancel a booked window, moving it `BOOKED → CANCELLED`; a cancelled slot's interval no longer participates in buffer checks for future bookings. Either transition from a non-booked state is `ERR_INVALID_STATE`.

Two terminal milestones close out the engagement. The Architect marks a project **substantially complete**, advancing `ACTIVE → SUBSTANTIALLY_COMPLETE`, only when every punch-list item on the project is `VERIFIED` — none left `OPEN`, `READY_FOR_REVIEW`, or `REOPENED`, a condition satisfied vacuously when there are no punch items — and at least one pay application on the project is `CERTIFIED`; otherwise `ERR_INVALID_STATE`. This sets the status and increments `Project.version` by one. Finally the Owner **closes** the project, advancing `SUBSTANTIALLY_COMPLETE → CLOSED`, only when the project's `retainage_held_cents` is zero (all retention released) and every subcontractor commitment on the project is `CLOSED`; otherwise `ERR_INVALID_STATE`. Closing sets the status and increments `Project.version` by one. `CLOSED` is terminal.

### 3.8. Retention Release and the Retainage Waterfall

Retainage accumulates on the schedule of values as pay applications certify, and it is released back to the Contractor through a **retention release**. A Contractor requests a release on a `project_id` with an `amount_cents` strictly greater than zero and the `expected_project_version` OCC guard. As a create against the project ledger, the request is subject to the stale-version guard of §2.6: if the project's `version` has advanced since the client read it, the create is rejected with `ERR_STALE_PROJECT_VERSION` (HTTP 412), so a drawdown is never sized against an out-of-date held-retainage balance. A new request opens in `REQUESTED`.

An Owner approves a requested release, advancing `REQUESTED → APPROVED`, only when the request is `REQUESTED`, the parent project is `ACTIVE` or `SUBSTANTIALLY_COMPLETE`, the body's `expected_project_version` equals the project's current `version` (else `ERR_STALE_PROJECT_VERSION`, HTTP 412), and the requested `amount_cents` is at most the project's current `retainage_held_cents` (else `ERR_RELEASE_EXCEEDS_HELD`, HTTP 422); a wrong-state or wrong-project-status approval is `ERR_INVALID_STATE`. On approval the system records the approving operator's opaque id as `approved_by_user_id` and runs the **retainage waterfall**. It distributes `amount_cents` across the project's `ACTIVE` schedule-of-values lines that currently hold retainage — those with `retainage_withheld_to_date_cents` greater than zero — taking them in ascending order of `item_no`, and within the same `item_no`, ascending `created_at`. For each line in turn it draws the smaller of the remaining amount and that line's `retainage_withheld_to_date_cents`, subtracts that draw from the line's withheld retainage, reduces the remaining amount by the same, and stops once the remaining amount reaches zero. Because approval already guaranteed the amount does not exceed the held total, the remaining amount always reaches zero with no overflow. A partial release draws down only the lowest-`item_no` lines until the amount is exhausted, leaving higher-numbered lines untouched; a full release equal to the held total zeroes every line's retainage and brings `retainage_held_cents` to zero, which is what later enables project close. After the waterfall the project's `retainage_held_cents` is recomputed as the sum of `retainage_withheld_to_date_cents` over its active lines, and `Project.version` is incremented by one. The alternative branch is rejection: an Owner may move a requested release `REQUESTED → REJECTED`, which performs no ledger mutation.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource return `201 Created`. Operations that modify an existing resource — every state transition, every workflow action — return `200 OK`. Read operations return `200 OK`. The request and response bodies, side effects, and preconditions for each operation are specified in the §3 narratives above; the table below is only a routing and authorization summary.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/projects` | Create a construction project | Owner |
| GET | `/projects/{id}` | Fetch a project with computed ledger fields | Owner, Contractor, Architect |
| GET | `/projects` | List projects | Owner, Contractor, Architect |
| POST | `/projects/{id}/substantial-completion` | Mark a project substantially complete | Architect |
| POST | `/projects/{id}/close` | Close out a substantially-complete project | Owner |
| POST | `/sov-lines` | Add a schedule-of-values line | Contractor |
| GET | `/sov-lines/{id}` | Fetch a schedule-of-values line | Owner, Contractor, Architect |
| GET | `/sov-lines` | List schedule-of-values lines | Owner, Contractor, Architect |
| POST | `/change-orders` | Draft a change order | Contractor |
| GET | `/change-orders/{id}` | Fetch a change order | Owner, Contractor, Architect |
| GET | `/change-orders` | List change orders | Owner, Contractor, Architect |
| POST | `/change-orders/{id}/submit` | Submit a draft change order | Contractor |
| POST | `/change-orders/{id}/approve` | Approve a submitted change order | Owner |
| POST | `/change-orders/{id}/reject` | Reject a submitted change order | Owner |
| POST | `/pay-applications` | Create a pay application draft | Contractor |
| GET | `/pay-applications/{id}` | Fetch a pay application | Owner, Contractor, Architect |
| GET | `/pay-applications` | List pay applications | Owner, Contractor, Architect |
| POST | `/pay-app-lines` | Add a billing line to a draft pay application | Contractor |
| GET | `/pay-app-lines/{id}` | Fetch a pay-app line | Owner, Contractor, Architect |
| GET | `/pay-app-lines` | List pay-app lines | Owner, Contractor, Architect |
| POST | `/pay-applications/{id}/submit` | Submit a pay application | Contractor |
| POST | `/pay-applications/{id}/certify` | Certify a submitted pay application | Architect |
| POST | `/pay-applications/{id}/reject` | Reject a submitted pay application | Architect |
| POST | `/subcontractor-commitments` | Record a subcontractor commitment | Contractor |
| GET | `/subcontractor-commitments/{id}` | Fetch a subcontractor commitment | Owner, Contractor, Architect |
| GET | `/subcontractor-commitments` | List subcontractor commitments | Owner, Contractor, Architect |
| POST | `/subcontractor-commitments/{id}/close` | Close a fully-invoiced commitment | Contractor |
| POST | `/rfis` | Log a request for information | Contractor |
| GET | `/rfis` | List RFIs | Owner, Contractor, Architect |
| GET | `/rfis/{id}` | Fetch an RFI | Owner, Contractor, Architect |
| POST | `/rfis/{id}/answer` | Answer an open RFI | Architect |
| POST | `/rfis/{id}/close` | Close an answered RFI | Contractor |
| POST | `/submittals` | Log a submittal | Contractor |
| GET | `/submittals` | List submittals | Owner, Contractor, Architect |
| GET | `/submittals/{id}` | Fetch a submittal | Owner, Contractor, Architect |
| POST | `/submittals/{id}/review` | Review a pending submittal | Architect |
| POST | `/submittals/{id}/resubmit` | Resubmit a revise-and-resubmit submittal | Contractor |
| POST | `/submittals/{id}/close` | Close an approved submittal | Architect |
| POST | `/lien-waivers` | Record a lien waiver | Contractor |
| GET | `/lien-waivers` | List lien waivers | Owner, Contractor, Architect |
| GET | `/lien-waivers/{id}` | Fetch a lien waiver | Owner, Contractor, Architect |
| POST | `/lien-waivers/{id}/notarize` | Make a pending lien waiver effective | Contractor |
| POST | `/lien-waivers/{id}/void` | Void a pending lien waiver | Owner |
| POST | `/punch-items` | Create a punch-list item | Architect |
| GET | `/punch-items` | List punch-list items | Owner, Contractor, Architect |
| GET | `/punch-items/{id}` | Fetch a punch-list item | Owner, Contractor, Architect |
| POST | `/punch-items/{id}/ready` | Mark a punch item ready for review | Contractor |
| POST | `/punch-items/{id}/verify` | Verify a punch item | Architect |
| POST | `/punch-items/{id}/reopen` | Reopen a punch item | Architect |
| POST | `/inspection-windows` | Book an inspection window | Contractor |
| GET | `/inspection-windows` | List inspection windows | Owner, Contractor, Architect |
| GET | `/inspection-windows/{id}` | Fetch an inspection window | Owner, Contractor, Architect |
| POST | `/inspection-windows/{id}/complete` | Mark an inspection window completed | Architect |
| POST | `/inspection-windows/{id}/cancel` | Cancel a booked inspection window | Contractor |
| POST | `/retention-releases` | Request a retention release | Contractor |
| GET | `/retention-releases` | List retention releases | Owner, Contractor, Architect |
| GET | `/retention-releases/{id}` | Fetch a retention release | Owner, Contractor, Architect |
| POST | `/retention-releases/{id}/approve` | Approve a retention release | Owner |
| POST | `/retention-releases/{id}/reject` | Reject a retention release | Owner |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_CROSS_PROJECT_REFERENCE` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 409 |
| `ERR_NONSEQUENTIAL_APPLICATION` | 422 |
| `ERR_BILLING_PERIOD_OVERLAP` | 409 |
| `ERR_INSPECTION_BUFFER_CONFLICT` | 409 |
| `ERR_DUPLICATE_ITEM_NO` | 409 |
| `ERR_LINE_EDITS_UNBALANCED` | 422 |
| `ERR_OVERBILLING` | 422 |
| `ERR_RELEASE_EXCEEDS_HELD` | 422 |
| `ERR_WAIVER_MISMATCH` | 422 |
| `ERR_PAYAPP_NOT_CERTIFIED` | 409 |
| `ERR_STALE_PROJECT_VERSION` | 412 |
| `ERR_INVALID_REQUEST` | 422 |
