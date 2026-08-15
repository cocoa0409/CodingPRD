# Physician Call Schedule & Locum Coverage API — Product Requirements Document

## 1. Introduction

Every service line in a hospital carries an after-hours obligation: on every weeknight, weekend, and holiday a named physician must be on call, and many programs also staff a backup who can be pressed into service when the primary is overwhelmed. Administering that obligation fairly is notoriously difficult. Holiday and weekend burden must be balanced across the roster, fatigue rules cap how much call any one physician may accumulate in a rolling month, payroll must stay inside an approved budget, and when coverage falls through, a locum tenens physician must be sourced and credentialed before the shift begins — not after.

This document specifies the Physician Call Schedule & Locum Coverage API, the system of record for that entire operation. A call program is configured with its calendar, staffing requirements, rates, and fairness weights; a deterministic generation engine builds call slots for every date in the period and auto-assigns staff physicians under eligibility filtering and fairness-point ranking. Once the rotation is published, physicians trade commitments through an equity-governed swap marketplace, coverage gaps are detected automatically and closed either by manual backfill or through a locum requisition pipeline with a five-item credentialing checklist and automatic placement on clearance, and every served call produces an immutable pay entry under a dual reserve-and-accrual payroll ledger. All deadline and window rules in the system read a server-side logical clock, so time-sensitive behavior is fully deterministic.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide contract: authentication, response envelopes, pagination, resource conventions, the logical clock, calendar and payroll arithmetic, fairness accounting, concurrency control, and the order in which validation failures surface. All endpoints are mounted under the `/api` prefix.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring their operational capacity. A request missing either header, or carrying a role the system does not recognize, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). The system recognizes four roles: `SchedulerAdmin`, `ChiefOfStaff`, `Physician`, and `CredentialingOfficer`. Every endpoint restricts which roles may invoke it; a caller whose role is not on that list is rejected with `ERR_FORBIDDEN` (HTTP 403).

The `SchedulerAdmin` is the medical staff office scheduler and owns the program lifecycle, the physician registry, unavailability approvals, manual assignments and serve sign-off, swap execution, locum requisitions, and the logical clock. The `ChiefOfStaff` approves or declines claimed swaps with equity oversight. The `CredentialingOfficer` runs locum credentialing cases. The `Physician` role is self-service: managing one's own unavailability windows, offering and claiming swaps, and activating one's own backup assignments.

Identity works two ways. When `X-User-Role` is `Physician`, `X-User-ID` is the `id` of the acting `Physician`; ownership checks on any resource that references a physician compare the resource's physician foreign-key field to `X-User-ID`. Concretely, a physician may create or cancel only their own unavailability windows, may offer or offerer-cancel swaps only on their own assignments, and may activate only a backup assignment where they are the assignee; violations are rejected with `ERR_OWNERSHIP_VIOLATION` (HTTP 403). When `X-User-Role` is `SchedulerAdmin`, `ChiefOfStaff`, or `CredentialingOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server never compares it to any entity's `id`.

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

Two system-level failures sit outside the per-endpoint checks of §2.11: a request that matches no route, or uses a method the route does not support, is rejected with `ERR_NOT_FOUND` (HTTP 404), and an unexpected server failure surfaces as `ERR_INVALID_REQUEST` (HTTP 400).

### 2.3. Pagination

List endpoints paginate through two query parameters. `limit` sets the maximum number of items returned; when omitted it defaults to 10, and it is bounded below by 1 and above by 100 — out-of-range values are clamped to those bounds rather than rejected, and a non-integer `limit` falls back to the default. `offset` sets the number of items skipped and defaults to 0, with negative values clamped to 0 and a non-integer `offset` falling back to the default. The `meta` object of a list response carries `limit`, `offset`, `total_count`, and `has_more`, where `has_more` is true exactly when `offset` plus the number of items returned is less than `total_count`.

Unless an endpoint pins its own ordering, list endpoints return resources sorted by `created_at` in ascending order. The call-slot listing is the one pinned exception — its chronological sort is specified in §3.3.

### 2.4. Common Resource Properties

All ten resources — CallProgram, Physician, UnavailabilityWindow, CallSlot, CallAssignment, SwapRequest, CoverageGap, LocumRequisition, CredentialingCase, and PayEntry — carry the same four system-managed properties. `id` is a server-minted UUID with no type prefix. `created_at` is an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created. `updated_at` is the same kind of timestamp, refreshed on every modification. `version` is an integer that starts at 1 when the resource is created and increments by one on every mutation.

### 2.5. The Logical Clock

Every rule in this document that says "now" reads a server-side logical clock — activation windows, serve times, swap cutoffs, credentialing deadlines, reconcile eligibility, and gap-detection timestamps all consult it. Before it has ever been set, the clock starts at exactly 2026-08-01T00:00:00Z, and it never falls back to wall-clock time. A `SchedulerAdmin`-only test-driving capability sets the clock to a supplied `to_iso8601` instant and returns the resulting `current_utc`; a `to_iso8601` value without an explicit offset is interpreted as UTC. Every timestamp derived from the logical clock — slot `window_start` and `window_end`, assignment `activated_at` and `served_at`, gap `detected_at`, case `clear_by`, checklist `completed_at` stamps, and the returned `current_utc` — serializes as ISO 8601 UTC, carrying three fractional digits when the fractional part is nonzero and no fractional digits when it is zero.

### 2.6. Call Windows and Calendar Classification

A call day runs from 07:00 UTC to 07:00 UTC the following day. Every slot's `window_start` is its `date` at 07:00:00Z, and its `window_end` is the next date at 07:00:00Z. The window is half-open: it includes the start instant and excludes the end instant. Every assignment against such a slot commits exactly 24 `call_hours`.

Each date inside a program carries a `date_type`: HOLIDAY when the date appears in the program's `holiday_dates`, otherwise WEEKEND when it falls on a Saturday or Sunday, otherwise WEEKDAY. HOLIDAY takes precedence over WEEKEND — a holiday that falls on a Sunday is paid and scored as a holiday.

Interval semantics differ deliberately by rule, and the distinction is load-bearing. Unavailability windows are closed date intervals: both `start_date` and `end_date` count as covered days, and two windows that touch on a single shared date overlap. Assignment conflict checks instead use half-open window overlap: two calls whose windows merely touch at 07:00 UTC do not conflict, so a physician may legitimately take consecutive call days.

Every date-valued request field — `period_start`, `period_end`, `start_date`, `end_date`, and each `holiday_dates` entry — must be an ISO `YYYY-MM-DD` string naming a valid calendar date; anything else fails request-shape validation with `ERR_INVALID_REQUEST`.

### 2.7. Payroll Ledgers and Monetary Precision

All monetary values in the system are integer cents. Each program maintains two computed totals. `payroll_reserved_cents` is the sum of `projected_pay_cents` over the program's assignments in SCHEDULED or ACTIVATED status, and it is updated on every assignment creation, cancellation, swap, and serve. `payroll_accrued_cents` is the sum of `amount_cents` over the program's pay entries in ACCRUED or FINALIZED status. A totals resync that changes either value refreshes the program's `updated_at` but does not by itself increment the program `version`; the version increments only on the operations whose narratives say so — in particular, the deactivation and window-approval cascades of §3.2 resync totals without bumping the version.

Rounding order is pinned. Each pay entry's amount is rounded half-up to whole cents at serve time, and the program totals sum the already-rounded integers. The alternative order — summing unrounded products and rounding once at the end — yields different cents and is forbidden.

A fiscal gate guards the three paths that create new commitments after generation: manual assignment creation, swap execution, and the credentialing auto-fill. On each, the resulting reserve — the current `payroll_reserved_cents` plus the new assignment's projected pay — must remain less than or equal to the program's `payroll_budget_cents`; equality is permitted, and a breach is rejected with `ERR_PAYROLL_BUDGET_EXCEEDED` (HTTP 402).

### 2.8. Fairness Points and the Equity Band

Fairness points quantify call burden. Each slot contributes its date-type points — `weekday_call_points` (default 1.0), `weekend_call_points` (default 2.0), or `holiday_call_points` (default 3.0) — multiplied by `backup_point_multiplier` (default 0.5) for BACKUP slots and by one for PRIMARY slots. Each slot's points are rounded half-up to two decimal places per slot, and only then summed; this per-slot rounding order is pinned and applies everywhere points are totaled.

Two variants are maintained for every physician within a program. Prospective points sum the physician's assignments in SCHEDULED, ACTIVATED, or SERVED status. Actual points sum SERVED assignments only, so identical data always yields actual totals less than or equal to prospective totals. SWAPPED and CANCELLED assignments feed neither variant. The equity band, `equity_band_points` (default 4.0), bounds how far above the population mean a swap may push a claimant, as specified in §3.4. Report means are rounded half-up to two decimal places.

### 2.9. Moonlighting Limits and Rolling-Hour Windows

Fatigue governance uses a rolling window of 28 dates: for a slot on date D, the window is the closed interval from 27 days before D through D itself.

For STAFF physicians, projected rolling hours are the sum of `call_hours` — 24 per assignment — over their assignments in SCHEDULED, ACTIVATED, or SERVED status whose slot dates fall inside that window. A new commitment is allowed only when the projected rolling hours plus the new call's own 24 hours remain less than or equal to the physician's `moonlight_cap_hours` (default 96). An exact fit is permitted; anything more is rejected with `ERR_MOONLIGHT_CAP_EXCEEDED`.

The premium tier rewards heavy recent service. For a STAFF physician, served hours before D are the sum over SERVED assignments whose slot dates fall from 27 days before D through the day before D — strictly before the slot date. When those served hours reach or exceed the program's `moonlight_premium_threshold_hours` (default 40), the premium multiplier of §3.3 applies to that call's pay. LOCUM physicians are exempt from both the cap and the premium.

### 2.10. Optimistic Concurrency Control

Regenerating a rotation is the only concurrency-guarded write in the API. The request must carry `expected_call_program_version`, holding the program's `version` as the client last observed it. If another writer has advanced the program's version since that read — most commonly by regenerating, which legitimately supersedes the prior slot and assignment set — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from rebuilding on top of a rotation it has not observed. Endpoints other than rotation regeneration do not accept a version field at all.

### 2.11. Validation Order and Error Precedence

When a request would fail several checks at once, the server reports the earliest failure in a fixed evaluation order rather than an arbitrary one. The §3 narratives state each endpoint's business checks in their actual evaluation order, and the ladder below fixes precedence wherever a narrative does not pin an order. On endpoints that must load a target resource before ownership can be evaluated, the load happens at the point of first use: that resource's 404 then precedes `ERR_OWNERSHIP_VIOLATION`, and any body-field validation not needed to locate the resource follows the load. The ladder:

1. Context headers — a missing or unrecognized `X-User-ID` or `X-User-Role` yields `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`.
2. Role permission — a role outside the endpoint's authorized list yields `ERR_FORBIDDEN`.
3. Ownership — for the entity-backed Physician role, acting on another physician's resources yields `ERR_OWNERSHIP_VIOLATION`.
4. Request shape — required fields present, types valid, enum members valid, `end_date` not earlier than `start_date`, `period_end` not earlier than `period_start`, all six required slot counts at least zero with at least one strictly positive; violations yield `ERR_INVALID_REQUEST`.
5. Existence — path identifiers are validated left-to-right, then body-referenced identifiers in their declared input order (so a manual-assignment request validates `slot_id` before `physician_id`); each unknown id surfaces its own 404: `ERR_PROGRAM_NOT_FOUND`, `ERR_PHYSICIAN_NOT_FOUND`, `ERR_SLOT_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_SWAP_NOT_FOUND`, `ERR_WINDOW_NOT_FOUND`, `ERR_GAP_NOT_FOUND`, `ERR_REQUISITION_NOT_FOUND`, `ERR_CASE_NOT_FOUND`, or `ERR_PAY_ENTRY_NOT_FOUND`.
6. State preconditions — the target entity must be in the phase the operation requires, else a 409 from the state family (`ERR_PROGRAM_NOT_DRAFT`, `ERR_PROGRAM_NOT_GENERATED`, `ERR_PROGRAM_NOT_PUBLISHED`, `ERR_REGENERATE_HAS_PROGRESS`, `ERR_UNRESOLVED_ASSIGNMENTS_EXIST`, `ERR_SLOT_NOT_OPEN`, `ERR_ASSIGNMENT_NOT_SCHEDULED`, `ERR_ASSIGNMENT_NOT_ACTIVATABLE`, `ERR_ASSIGNMENT_NOT_SERVABLE`, `ERR_SWAP_NOT_POSTED`, `ERR_SWAP_NOT_CLAIMED`, `ERR_SWAP_NOT_APPROVED`, `ERR_SWAP_ASSIGNMENT_NOT_SCHEDULED`, `ERR_WINDOW_NOT_REQUESTED`, `ERR_WINDOW_NOT_CANCELLABLE`, `ERR_GAP_NOT_OPEN`, `ERR_REQUISITION_NOT_OPEN`, `ERR_REQUISITION_NOT_SOURCED`, `ERR_REQUISITION_NOT_CANCELLABLE`, `ERR_CASE_NOT_ACTIVE`, and the deactivate-time `ERR_PHYSICIAN_INACTIVE`).
7. Stale version — the regeneration OCC check, `ERR_STALE_VERSION`.
8. Business safety — physician active for new commitments, unavailability conflicts, the moonlight cap, window approval covering served work, credentialing prerequisites: `ERR_PHYSICIAN_INACTIVE`, `ERR_UNAVAILABILITY_CONFLICT`, `ERR_MOONLIGHT_CAP_EXCEEDED`, `ERR_WINDOW_COVERS_SERVED_ASSIGNMENT`, `ERR_PREREQUISITE_ITEM_INCOMPLETE`.
9. Temporal rules — `ERR_WINDOW_OVERLAP`, `ERR_ASSIGNMENT_OVERLAP`, `ERR_SWAP_CUTOFF_VIOLATION`, `ERR_SERVE_BEFORE_WINDOW_END`, `ERR_ACTIVATION_WINDOW_CLOSED`, `ERR_SLOT_WINDOW_PASSED`, `ERR_CREDENTIALING_DEADLINE_PASSED`, `ERR_CREDENTIALING_NOT_EXPIRED`, `ERR_CREDENTIALING_INFEASIBLE`, `ERR_PERIOD_NOT_ENDED`.
10. Business constraints — `ERR_SPECIALTY_MISMATCH`, `ERR_MANUAL_ASSIGNMENT_STAFF_ONLY`, `ERR_SWAP_CLAIMANT_INELIGIBLE`, `ERR_CANDIDATE_NOT_LOCUM`, `ERR_SELF_SWAP`, `ERR_DUPLICATE_ACTIVE_SWAP`, `ERR_ITEM_ALREADY_COMPLETED`, `ERR_SWAP_EQUITY_BREACH`, `ERR_ACTIVATION_REQUIRES_BACKUP_SLOT`.
11. The fiscal gate — `ERR_PAYROLL_BUDGET_EXCEEDED` — always evaluated last.

## 3. Business Logic & Workflows

### 3.1. Building the Rotation: Program Setup, Generation, and Publication

A `SchedulerAdmin` opens a scheduling cycle by creating a call program: a display `name`, the `service_line` specialty namespace the rotation covers, and a closed scheduling period running from `period_start` through `period_end` — an end earlier than the start is rejected as `ERR_INVALID_REQUEST`. Fiscal configuration is anchored by `payroll_budget_cents`, a required, strictly positive cap on reserved payroll. Calendar configuration comprises the optional `holiday_dates` (default empty; listed dates inside the period are classified HOLIDAY with precedence over WEEKEND; a non-array value or an entry that is not a valid ISO date string is `ERR_INVALID_REQUEST`) and six staffing counts: `weekday_primary_required`, `weekend_primary_required`, and `holiday_primary_required` each default to 1, while `weekday_backup_required`, `weekend_backup_required`, and `holiday_backup_required` each default to 0. Every count must be at least zero, and at least one of the six must be strictly positive, or creation fails with `ERR_INVALID_REQUEST`. The remaining tuning knobs — stipend rates, pay multipliers, point weights, the equity band, the swap cutoff, and the credentialing lead time — are optional at creation with the defaults given in §2.6 through §2.9 and §3.3 through §3.5, and beyond their types they accept any value without further range validation. A new program is DRAFT, with `payroll_reserved_cents` and `payroll_accrued_cents` at zero and `version` at 1. Program listings may be filtered by `status` and `service_line`.

Generation turns a DRAFT program into a GENERATED one; attempting it in any other phase is `ERR_PROGRAM_NOT_DRAFT`. The engine enumerates every date in the closed period, classifies its `date_type` per §2.6, and creates that date's primary count of PRIMARY slots and backup count of BACKUP slots, numbering each same-date, same-type group with a 1-based `position_index`. Rotation auto-assignment then fills them: PRIMARY slots are processed in ascending date order with ties broken by `position_index`, followed by BACKUP slots in the same order. For each slot, the eligible pool is every STAFF physician who is ACTIVE, whose `specialty` equals the program's `service_line`, who holds no APPROVED unavailability window covering the slot date, who has no overlapping commitment in SCHEDULED, ACTIVATED, or SERVED status — including tentative assignments created earlier in the same run — and whose projected rolling hours, again including tentative assignments, plus 24 stay within their `moonlight_cap_hours`. The slot goes to the physician with the lowest prospective total points including tentative assignments; ties break toward the lowest prospective undesirable points — the weekend-and-holiday portion of the total — and then toward the earliest physician `created_at`. UUIDs are never decision inputs, and each tentative assignment immediately counts toward later slots in the same run. Every filled slot yields a CallAssignment with `origin` GENERATED in SCHEDULED status and the slot becomes ASSIGNED; every slot whose pool is empty stays OPEN and opens a CoverageGap with `reason` GENERATION_SHORTFALL. The reserve is updated from the new assignments' projected pay, and the program `version` increments.

Regeneration rebuilds the rotation in place as a GENERATED to GENERATED self-loop. It requires the program to be GENERATED (`ERR_PROGRAM_NOT_GENERATED`), requires that no assignment in the program be ACTIVATED or SERVED (`ERR_REGENERATE_HAS_PROGRESS`), and applies the OCC rule of §2.10 — a request whose `expected_call_program_version` no longer matches is rejected with `ERR_STALE_VERSION`. Regeneration deletes all of the program's existing slots, assignments, and coverage gaps — only GENERATED-origin SCHEDULED assignments can exist before publication — then re-runs slot creation and rotation auto-assignment exactly as generation does, recomputes the reserve from the new assignments, and increments the program `version`.

Publication moves the program from GENERATED to PUBLISHED (`ERR_PROGRAM_NOT_GENERATED` otherwise) and unlocks the operational phase: manual assignments and the swap marketplace exist only against PUBLISHED programs. Publication increments the program `version`.

### 3.2. The Physician Registry and Unavailability Windows

A `SchedulerAdmin` registers physicians with a `full_name`, a `specialty`, and an `employment_type` of STAFF or LOCUM; `moonlight_cap_hours` is optional and defaults to 96, and a supplied value must be strictly positive or registration fails with `ERR_INVALID_REQUEST`. New physicians are ACTIVE. LOCUM physicians sit outside the fairness and fatigue apparatus — exempt from the moonlight cap and the premium tier — and may be placed only through the requisition pipeline of §3.5, never by direct assignment. Physician listings may be filtered by `employment_type`, `status`, and `specialty`.

Deactivation moves a physician from ACTIVE to INACTIVE; deactivating an already-INACTIVE physician is rejected with `ERR_PHYSICIAN_INACTIVE`. The transition cascades deliberately. Every SCHEDULED assignment of the physician whose slot's `window_end` is still in the future is CANCELLED. Each such cancellation reopens its slot from ASSIGNED to OPEN, opens a CoverageGap with `reason` PHYSICIAN_DEACTIVATED, and releases that assignment's projected pay from the reserve. The swap cascade follows: any swap in POSTED, CLAIMED, or APPROVED status that references a cancelled assignment is CANCELLED, and any swap in those states whose offerer or claimant is the deactivated physician is likewise CANCELLED.

Unavailability windows record vacation, CME, and personal time away from call. A Physician creates windows only for themself, while a `SchedulerAdmin` may create them for anyone; the request carries `physician_id`, `start_date`, and `end_date` as a closed date interval — an end before the start is `ERR_INVALID_REQUEST`, and a Physician caller whose `physician_id` differs from their own `X-User-ID` is `ERR_OWNERSHIP_VIOLATION` — plus an optional `kind` of VACATION, CME, or PERSONAL, defaulting to VACATION. New windows are REQUESTED, and listings filter by `physician_id` and `status`.

Approval moves REQUESTED to APPROVED (any other phase is `ERR_WINDOW_NOT_REQUESTED`) and is a `SchedulerAdmin` decision with two guards. First, no ACTIVATED or SERVED assignment of the physician may have its slot date inside the window — activated or served calls cannot be retroactively uncovered — and such a request is `ERR_WINDOW_COVERS_SERVED_ASSIGNMENT`. Second, no other APPROVED window of the same physician may overlap the requested closed interval — because the intervals are closed, windows that touch on a single date overlap, and such a request is rejected with `ERR_WINDOW_OVERLAP`. When approval succeeds it cascades: every SCHEDULED assignment of the physician whose slot date falls inside the closed window is CANCELLED; each cancellation reopens its slot from ASSIGNED to OPEN, opens a CoverageGap with `reason` ASSIGNMENT_CANCELLED, releases the assignment's projected pay from the reserve, and cancels any non-terminal swap referencing the cancelled assignment.

Cancellation moves a REQUESTED or APPROVED window to CANCELLED — any other phase is `ERR_WINDOW_NOT_CANCELLABLE` — and is available to the owning Physician or a `SchedulerAdmin`. Cancellation has no side effects; in particular, cancelling an APPROVED window does not restore the assignments its approval cancelled.

### 3.3. Working the Schedule: Assignments, Backup Activation, and Serving

Call slots are created by generation and are read-only thereafter. Slot listings may be filtered by `program_id`, `date`, `call_type`, `date_type`, and `status`, and they use a pinned sort order that overrides the default creation-time ordering: `date` ascending, then `call_type` ascending — which places BACKUP before PRIMARY — then `position_index` ascending.

Manual assignment is the backfill tool: a `SchedulerAdmin` places a STAFF physician onto an OPEN slot of a PUBLISHED program, producing an assignment with `origin` MANUAL. The request carries `slot_id` and `physician_id`, validated in that order per §2.11. The guards then accumulate across the precedence ladder: the program must be PUBLISHED (`ERR_PROGRAM_NOT_PUBLISHED`) and the slot OPEN (`ERR_SLOT_NOT_OPEN`); the physician must be ACTIVE (`ERR_PHYSICIAN_INACTIVE`); no APPROVED unavailability window of the physician may cover the slot date (`ERR_UNAVAILABILITY_CONFLICT`); the moonlight cap applies with its exact-fit-permitted semantics (`ERR_MOONLIGHT_CAP_EXCEEDED`); the new commitment must not half-open-overlap any of the physician's SCHEDULED, ACTIVATED, or SERVED assignments — adjacent call days are allowed (`ERR_ASSIGNMENT_OVERLAP`); and the slot window must not already have ended (`ERR_SLOT_WINDOW_PASSED`). The physician's `specialty` must equal the program's `service_line` (`ERR_SPECIALTY_MISMATCH`), and a LOCUM physician is refused outright with `ERR_MANUAL_ASSIGNMENT_STAFF_ONLY`, because locums are placed only via the requisition flow. Finally the fiscal gate of §2.7 applies (`ERR_PAYROLL_BUDGET_EXCEEDED`). On creation the slot moves OPEN → ASSIGNED; the projected pay variant is computed — activation assumed absent, the premium tier evaluated on projected (SCHEDULED, ACTIVATED, and SERVED) hours over the same strictly-before-the-slot-date rolling window of §2.9 — and stored in `projected_pay_cents`; the reserve increases by that amount; and the program `version` increments. When the slot had an OPEN or REQUISITIONED coverage gap, the gap becomes RESOLVED with `resolved_by_assignment_id` set to the new assignment; if that gap was attached to a locum requisition in OPEN, SOURCED, or CREDENTIALING status, the requisition is CANCELLED and its active credentialing case is CANCELLED with it.

Backup activation is how a scheduled backup is pressed into service. The assignee — a Physician caller must be the assignee, otherwise `ERR_OWNERSHIP_VIOLATION` — or a `SchedulerAdmin` activates an assignment that is SCHEDULED (`ERR_ASSIGNMENT_NOT_ACTIVATABLE`), at a moment inside the activation window that runs from `window_start` through two hours after `window_end`, both bounds inclusive (outside it, `ERR_ACTIVATION_WINDOW_CLOSED`), and whose slot is BACKUP (`ERR_ACTIVATION_REQUIRES_BACKUP_SLOT`). The request carries a `reason`. Activation stamps `activated_at` and moves the assignment SCHEDULED → ACTIVATED; the pay consequences arrive at serve time through the activation multiplier.

Serving closes the loop. A `SchedulerAdmin` marks an assignment served from SCHEDULED or ACTIVATED — anything else is `ERR_ASSIGNMENT_NOT_SERVABLE` — and never before the slot's `window_end` has arrived (`ERR_SERVE_BEFORE_WINDOW_END`). Serving stamps `served_at`, moves the slot ASSIGNED → COVERED, and creates the pay entry in ACCRUED status. The actual pay variant takes the base rate for the slot's call type — `primary_rate_cents` (default 50,000 cents) or `backup_rate_cents` (default 20,000 cents), snapshotted onto the entry as `base_rate_cents` — multiplies it by the date multiplier (`holiday_multiplier`, default 1.5, on HOLIDAY dates; `weekend_multiplier`, default 1.25, on WEEKEND dates; one on WEEKDAY dates), then by `backup_activation_multiplier` (default 2.0) when the assignment was ACTIVATED before serving and by one otherwise, and then by `moonlight_premium_multiplier` (default 1.15) when a STAFF physician reached the premium tier of §2.9 on served-only hours and by one otherwise; the product is rounded half-up to whole cents in exactly one rounding step, applied after all multipliers, and stored immutably as `amount_cents`. The entry records which multipliers fired through `activation_applied` and `premium_applied`, and copies `slot_date`, `call_type`, and `date_type` from the slot alongside its `assignment_id`, `physician_id`, and `program_id`. Serving an activated backup therefore pays more than its projection — the projected and actual variants diverge by design. The reserve releases the assignment's projected pay, `payroll_accrued_cents` increases by `amount_cents`, and the program `version` increments.

Cancellation applies only to SCHEDULED assignments (`ERR_ASSIGNMENT_NOT_SCHEDULED`; an ACTIVATED assignment cannot be cancelled). The slot returns ASSIGNED → OPEN, a CoverageGap with `reason` ASSIGNMENT_CANCELLED is opened, the assignment's projected pay is released from the reserve, any swap in POSTED, CLAIMED, or APPROVED status referencing the assignment is CANCELLED, and the program `version` increments. A slot may cycle OPEN → ASSIGNED → OPEN any number of times before it is finally COVERED. Assignment listings filter by `program_id`, `slot_id`, `physician_id`, `status`, `origin`, `source_swap_id`, and `source_requisition_id`.

### 3.4. The Swap Marketplace

A Physician opens the marketplace by offering one of their own SCHEDULED assignments. The request carries `assignment_id`; the assignment must belong to the caller (`ERR_OWNERSHIP_VIOLATION`), must be SCHEDULED (`ERR_SWAP_ASSIGNMENT_NOT_SCHEDULED`), must sit in a PUBLISHED program (`ERR_PROGRAM_NOT_PUBLISHED`), and must not already be referenced by another swap in POSTED, CLAIMED, or APPROVED status (`ERR_DUPLICATE_ACTIVE_SWAP`). The new swap is POSTED, with `offerer_physician_id` copied from the assignment and `program_id` denormalized onto the swap. Swap listings filter by `program_id`, `assignment_id`, `offerer_physician_id`, `claimant_physician_id`, and `status`.

Claiming moves a swap from POSTED to CLAIMED — any other phase is `ERR_SWAP_NOT_POSTED`. The claimant is the registered physician identified by the caller's `X-User-ID`; an unregistered id is `ERR_PHYSICIAN_NOT_FOUND`. The claimant must be a STAFF physician (`ERR_SWAP_CLAIMANT_INELIGIBLE`), ACTIVE (`ERR_PHYSICIAN_INACTIVE`), and someone other than the offerer (`ERR_SELF_SWAP`); their `specialty` must match the program's `service_line` (`ERR_SPECIALTY_MISMATCH`); no APPROVED unavailability window of theirs may cover the slot date (`ERR_UNAVAILABILITY_CONFLICT`); the call must not overlap their existing SCHEDULED, ACTIVATED, or SERVED commitments (`ERR_ASSIGNMENT_OVERLAP`); and their projected rolling hours plus the call's 24 must fit within `moonlight_cap_hours` (`ERR_MOONLIGHT_CAP_EXCEEDED`). The claim must also arrive in time: the slot's `window_start` must be at least `swap_cutoff_hours` (default 48 hours) in the future — a claim exactly at the cutoff is allowed, anything later is `ERR_SWAP_CUTOFF_VIOLATION`. A successful claim sets `claimant_physician_id` to the caller's `X-User-ID`.

Approval is the `ChiefOfStaff`'s equity review, moving CLAIMED → APPROVED (anything else is `ERR_SWAP_NOT_CLAIMED`). The referenced assignment must still be SCHEDULED (`ERR_SWAP_ASSIGNMENT_NOT_SCHEDULED`) and the program still PUBLISHED (`ERR_PROGRAM_NOT_PUBLISHED`). The equity check then recomputes prospective points as they would stand after the swap — the claimant credited with the slot's points and the offerer relieved of them, per the status-filtered point sets of §2.8 — and rejects the approval with `ERR_SWAP_EQUITY_BREACH` when the claimant's post-swap prospective total would be strictly greater than the post-swap population mean of prospective points — recomputed over the post-swap population and rounded half-up to two decimal places before the comparison — plus the program's `equity_band_points`; landing exactly on that boundary is permitted. Decline is the sibling action, moving CLAIMED back to POSTED, clearing `claimant_physician_id` to null, and recording the optional `decline_reason` — set to the supplied value, or to null when the decline carries none. A swap may cycle through claim and decline repeatedly before it is finally approved or withdrawn.

Execution, performed by a `SchedulerAdmin`, turns APPROVED into EXECUTED (`ERR_SWAP_NOT_APPROVED` otherwise) and re-verifies everything that could have drifted since approval: the referenced assignment still SCHEDULED (`ERR_SWAP_ASSIGNMENT_NOT_SCHEDULED`); the slot's `window_start` still strictly in the future (`ERR_SLOT_WINDOW_PASSED`); the claimant's eligibility re-checked on unavailability (`ERR_UNAVAILABILITY_CONFLICT`), overlap (`ERR_ASSIGNMENT_OVERLAP`), and the moonlight cap (`ERR_MOONLIGHT_CAP_EXCEEDED`); and the fiscal gate applied to the replacement's projected pay (`ERR_PAYROLL_BUDGET_EXCEEDED`). Execution moves the original assignment SCHEDULED → SWAPPED and creates the replacement CallAssignment for the claimant with `origin` SWAP, `source_swap_id` set to the swap, SCHEDULED status, and projected pay computed for the claimant. The slot remains ASSIGNED throughout. The reserve adjusts by the difference between the replacement's and the original's projected pay; fairness-point ownership passes from offerer to claimant through the status-filtered sets; and the program `version` increments.

The offerer may cancel a swap only on their own offers (`ERR_OWNERSHIP_VIOLATION`) and only while it is POSTED (`ERR_SWAP_NOT_POSTED`); a CLAIMED swap must first be declined by the `ChiefOfStaff` before the offerer can cancel it. Independently of any user action, the system cancels any swap in POSTED, CLAIMED, or APPROVED status when its referenced assignment is cancelled or swapped away, or when its offerer or claimant is deactivated.

### 3.5. Coverage Gaps and the Locum Pipeline

Coverage gaps are the system's early-warning record, opened automatically with `reason` GENERATION_SHORTFALL by generation, ASSIGNMENT_CANCELLED by assignment cancellation or unavailability approval, or PHYSICIAN_DEACTIVATED by deactivation. `detected_at` stamps the logical-clock moment of detection, and `resolved_by_assignment_id` stays null until the gap is resolved. A gap moves OPEN → REQUISITIONED when a requisition is opened against it, REQUISITIONED → OPEN only when that requisition is cancelled, and OPEN or REQUISITIONED → RESOLVED when an assignment is created for its slot — by manual backfill, regeneration, or locum fill — with `resolved_by_assignment_id` set to the resolving assignment. Symmetrically, when a cancellation cascade cancels the very assignment that resolved a gap, that same gap record is re-opened — returned to OPEN with `resolved_by_assignment_id` cleared and its `reason` and `detected_at` re-stamped — rather than a fresh gap record being created. Note the deliberate asymmetry: a failed or expired credentialing case re-opens the requisition but leaves the gap REQUISITIONED. Gap listings filter by `program_id`, `slot_id`, `status`, `reason`, and `resolved_by_assignment_id`.

A `SchedulerAdmin` opens a locum requisition against an OPEN gap — any other gap phase is `ERR_GAP_NOT_OPEN` — by supplying the `gap_id`, and only while credentialing remains feasible: the logical clock must be strictly earlier than the slot's `window_start` minus the program's `credentialing_lead_hours` (default 120 hours, five days of lead time), or creation fails with `ERR_CREDENTIALING_INFEASIBLE`. The requisition is created OPEN with `program_id` denormalized from the gap. Requisition listings filter by `gap_id`, `program_id`, `candidate_physician_id`, and `status`.

Candidate proposal moves OPEN → SOURCED (otherwise `ERR_REQUISITION_NOT_OPEN`). The request carries `candidate_physician_id`; the candidate must be ACTIVE (`ERR_PHYSICIAN_INACTIVE`), free of any APPROVED unavailability window covering the slot date (`ERR_UNAVAILABILITY_CONFLICT`), free of overlapping SCHEDULED, ACTIVATED, or SERVED commitments (`ERR_ASSIGNMENT_OVERLAP`), a LOCUM physician (a STAFF nominee is `ERR_CANDIDATE_NOT_LOCUM`), and specialty-matched to the program (`ERR_SPECIALTY_MISMATCH`). As a LOCUM, the candidate is not subject to the moonlight cap. A successful proposal sets `candidate_physician_id`.

Beginning credentialing is the `CredentialingOfficer`'s step, moving SOURCED → CREDENTIALING (`ERR_REQUISITION_NOT_SOURCED` otherwise) and requiring the same feasibility window — the logical clock strictly earlier than `window_start` minus the lead hours, else `ERR_CREDENTIALING_INFEASIBLE`. This creates a CredentialingCase in INITIATED status with `requisition_id` and `locum_physician_id` set, a `clear_by` deadline equal to the slot's `window_start` minus `credentialing_lead_hours`, and an `items` object keyed by the five item names, each value holding a `completed_at` timestamp or null: `license_verification`, `malpractice_verification`, `privileges_granting`, `health_screening`, and `orientation`. The endpoint responds with the updated requisition; the new case is read through its own endpoints. Case listings filter by `requisition_id`, `locum_physician_id`, and `status`.

Completing checklist items is item-by-item work. Each completion request names an `item`; the case must be INITIATED or IN_PROGRESS (`ERR_CASE_NOT_ACTIVE`); `privileges_granting` additionally requires `license_verification` to be completed first (`ERR_PREREQUISITE_ITEM_INCOMPLETE`); the logical clock must be at or before `clear_by` — exactly at the deadline is permitted, later is `ERR_CREDENTIALING_DEADLINE_PASSED`; and an item already completed is rejected with `ERR_ITEM_ALREADY_COMPLETED`. Each accepted completion stamps that item's `completed_at`. The first item moves the case INITIATED → IN_PROGRESS, and the fifth and final item moves it IN_PROGRESS → CLEARED, firing the auto-fill cascade in the same breath: the requisition advances CREDENTIALING → READY → FILLED, with READY transient inside the cascade; a CallAssignment is created for the candidate with `origin` LOCUM_FILL, `source_requisition_id` set, SCHEDULED status, and projected pay computed; the slot moves OPEN → ASSIGNED; the gap becomes RESOLVED with `resolved_by_assignment_id` set; and the reserve increases by the new projected pay, subject to the fiscal gate (`ERR_PAYROLL_BUDGET_EXCEEDED`). A gate breach rejects the completion request as a whole — the fifth item is not stamped and the case remains IN_PROGRESS.

Two off-ramps handle cases that cannot complete. Failing a case — the request carries a `reason` — requires the case INITIATED or IN_PROGRESS (`ERR_CASE_NOT_ACTIVE`) and moves it to FAILED. Expiring a case requires the same active phases and additionally that the logical clock be strictly past `clear_by` (at or before the deadline, `ERR_CREDENTIALING_NOT_EXPIRED`), moving it to EXPIRED. Both outcomes re-open the requisition from CREDENTIALING to OPEN, clear its `candidate_physician_id` to null, and leave the gap REQUISITIONED; the OPEN → SOURCED → CREDENTIALING → OPEN cycle may repeat for as many candidates as needed.

A `SchedulerAdmin` may cancel a requisition from OPEN, SOURCED, or CREDENTIALING — any other phase is `ERR_REQUISITION_NOT_CANCELLABLE`. Cancelling from CREDENTIALING also moves the active CredentialingCase to CANCELLED, and the case is likewise CANCELLED automatically whenever its parent requisition is cancelled. Cancellation returns the gap from REQUISITIONED to OPEN and clears the candidate — except when the trigger was a manual backfill resolving the gap, in which case the gap ends RESOLVED rather than OPEN.

### 3.6. Payroll, Reporting, and Reconciliation

Pay entries are created only at serve time, as §3.3 describes; each begins ACCRUED and is finalized at reconciliation. Pay-entry listings filter by `program_id`, `assignment_id`, `physician_id`, and `status`. The two program totals — `payroll_reserved_cents` over SCHEDULED and ACTIVATED assignments, `payroll_accrued_cents` over ACCRUED and FINALIZED entries — follow the pinned per-entry rounding of §2.7.

The fairness report is a computed per-program read. Its population is every physician holding at least one SCHEDULED, ACTIVATED, or SERVED assignment in the program, and it returns the `program_id`, the `population_size`, `total_prospective_points` and `total_actual_points` across that population, `mean_prospective_points` and `mean_actual_points` — each mean being the corresponding total divided by the population size, rounded half-up to two decimal places — the program's `equity_band_points`, and the per-physician `entries`. Each entry carries `physician_id`, `full_name`, `prospective_points`, and `actual_points`, and entries are ordered by the physician's `created_at` ascending; when the population is empty, both totals and both means are 0.00. Because prospective points count SCHEDULED and ACTIVATED commitments in addition to SERVED work while actual points count SERVED work alone, identical data always yields actual totals less than or equal to prospective totals.

The coverage report is the compliance read. For each date in the closed period it derives the required primary and backup counts from the date-type staffing fields, counts covered slots as those in ASSIGNED or COVERED status, and computes each shortfall as the required count minus the covered count, floored at zero. A date is compliant when its covered primary count meets or exceeds the required primary count and its covered backup count meets or exceeds the required backup count — exact coverage counts as compliant. The report returns the `program_id`, the `compliant_date_count`, the `noncompliant_date_count`, the `open_gap_count` — gaps still in OPEN or REQUISITIONED status — and the per-date `dates` breakdown in ascending date order, each entry carrying `date`, `date_type`, `required_primary`, `covered_primary`, `shortfall_primary`, `required_backup`, `covered_backup`, `shortfall_backup`, and `compliant`.

Reconciliation is the closing act, moving the program PUBLISHED → RECONCILED. It requires the program PUBLISHED (`ERR_PROGRAM_NOT_PUBLISHED`), requires every assignment in the program to be terminal — SERVED, SWAPPED, or CANCELLED — (`ERR_UNRESOLVED_ASSIGNMENTS_EXIST`), and requires the logical clock to have reached 00:00:00 UTC on the day after `period_end` (`ERR_PERIOD_NOT_ENDED`). Reconciliation moves every ACCRUED pay entry to FINALIZED, moves every slot still OPEN to UNCOVERED, and increments the program `version`. It does not alter coverage gaps, locum requisitions, credentialing cases, or swap requests. RECONCILED is terminal.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created` — program creation, physician registration, unavailability-window requests, manual assignments, swap postings, and locum-requisition creation. All other mutations, and every read, return `200 OK`. Request payloads, response shapes, and side effects are specified per workflow in §3; the table below is the routing and authorization reference only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/call-programs` | Create a call program (DRAFT) | SchedulerAdmin |
| GET | `/api/call-programs` | List call programs | SchedulerAdmin, ChiefOfStaff, Physician, CredentialingOfficer |
| GET | `/api/call-programs/{id}` | Get a call program | SchedulerAdmin, ChiefOfStaff, Physician, CredentialingOfficer |
| POST | `/api/call-programs/{id}/generate` | Generate slots and run rotation auto-assignment (DRAFT → GENERATED) | SchedulerAdmin |
| POST | `/api/call-programs/{id}/regenerate` | Rebuild the rotation in place; OCC-guarded (GENERATED → GENERATED) | SchedulerAdmin |
| POST | `/api/call-programs/{id}/publish` | Publish the rotation (GENERATED → PUBLISHED) | SchedulerAdmin |
| POST | `/api/call-programs/{id}/reconcile` | Reconcile after period end (PUBLISHED → RECONCILED); finalizes pay | SchedulerAdmin |
| GET | `/api/call-programs/{id}/fairness-report` | Computed fairness report: prospective and actual points, means, equity band | SchedulerAdmin, ChiefOfStaff, Physician, CredentialingOfficer |
| GET | `/api/call-programs/{id}/coverage-report` | Computed coverage compliance report | SchedulerAdmin, ChiefOfStaff, Physician, CredentialingOfficer |
| POST | `/api/physicians` | Register a physician (STAFF or LOCUM), ACTIVE | SchedulerAdmin |
| GET | `/api/physicians` | List physicians | SchedulerAdmin, ChiefOfStaff, Physician, CredentialingOfficer |
| GET | `/api/physicians/{id}` | Get a physician | SchedulerAdmin, ChiefOfStaff, Physician, CredentialingOfficer |
| POST | `/api/physicians/{id}/deactivate` | Deactivate a physician; cascade-cancels future commitments and related swaps | SchedulerAdmin |
| POST | `/api/unavailability-windows` | Request an unavailability window (REQUESTED); Physician role creates for self only | Physician, SchedulerAdmin |
| GET | `/api/unavailability-windows` | List unavailability windows | SchedulerAdmin, ChiefOfStaff, Physician, CredentialingOfficer |
| GET | `/api/unavailability-windows/{id}` | Get an unavailability window | SchedulerAdmin, ChiefOfStaff, Physician, CredentialingOfficer |
| POST | `/api/unavailability-windows/{id}/approve` | Approve a window; cascade-cancels conflicting SCHEDULED assignments | SchedulerAdmin |
| POST | `/api/unavailability-windows/{id}/cancel` | Cancel a REQUESTED or APPROVED window; does not restore cancelled assignments | Physician, SchedulerAdmin |
| GET | `/api/call-slots` | List call slots; pinned sort: date, then call type (BACKUP before PRIMARY), then position index | SchedulerAdmin, ChiefOfStaff, Physician, CredentialingOfficer |
| GET | `/api/call-slots/{id}` | Get a call slot | SchedulerAdmin, ChiefOfStaff, Physician, CredentialingOfficer |
| POST | `/api/call-assignments` | Manually assign a STAFF physician to an OPEN slot of a PUBLISHED program (MANUAL) | SchedulerAdmin |
| GET | `/api/call-assignments` | List call assignments | SchedulerAdmin, ChiefOfStaff, Physician, CredentialingOfficer |
| GET | `/api/call-assignments/{id}` | Get a call assignment | SchedulerAdmin, ChiefOfStaff, Physician, CredentialingOfficer |
| POST | `/api/call-assignments/{id}/cancel` | Cancel a SCHEDULED assignment; opens a coverage gap | SchedulerAdmin |
| POST | `/api/call-assignments/{id}/mark-served` | Sign off a completed call (SCHEDULED/ACTIVATED → SERVED); creates the pay entry | SchedulerAdmin |
| POST | `/api/call-assignments/{id}/activate-backup` | Activate a BACKUP assignment inside its activation window | Physician, SchedulerAdmin |
| POST | `/api/swap-requests` | Offer one of the caller's SCHEDULED assignments for swap (POSTED) | Physician |
| GET | `/api/swap-requests` | List swap requests | SchedulerAdmin, ChiefOfStaff, Physician, CredentialingOfficer |
| GET | `/api/swap-requests/{id}` | Get a swap request | SchedulerAdmin, ChiefOfStaff, Physician, CredentialingOfficer |
| POST | `/api/swap-requests/{id}/claim` | Claim a POSTED swap; full claimant eligibility check including the cutoff | Physician |
| POST | `/api/swap-requests/{id}/approve` | Chief-of-staff approval; re-validates assignment state and the equity band | ChiefOfStaff |
| POST | `/api/swap-requests/{id}/decline` | Chief-of-staff decline; the swap returns to POSTED with claimant cleared | ChiefOfStaff |
| POST | `/api/swap-requests/{id}/execute` | Execute an APPROVED swap; re-checks claimant eligibility; transfers the assignment | SchedulerAdmin |
| POST | `/api/swap-requests/{id}/cancel` | Offerer cancels a POSTED swap | Physician |
| GET | `/api/coverage-gaps` | List coverage gaps | SchedulerAdmin, ChiefOfStaff, Physician, CredentialingOfficer |
| GET | `/api/coverage-gaps/{id}` | Get a coverage gap | SchedulerAdmin, ChiefOfStaff, Physician, CredentialingOfficer |
| POST | `/api/locum-requisitions` | Open a locum requisition for an OPEN gap; requires the credentialing window to be feasible | SchedulerAdmin |
| GET | `/api/locum-requisitions` | List locum requisitions | SchedulerAdmin, ChiefOfStaff, Physician, CredentialingOfficer |
| GET | `/api/locum-requisitions/{id}` | Get a locum requisition | SchedulerAdmin, ChiefOfStaff, Physician, CredentialingOfficer |
| POST | `/api/locum-requisitions/{id}/propose-candidate` | Propose a LOCUM candidate (OPEN → SOURCED) | SchedulerAdmin |
| POST | `/api/locum-requisitions/{id}/begin-credentialing` | Open a credentialing case for the sourced candidate (SOURCED → CREDENTIALING) | CredentialingOfficer |
| POST | `/api/locum-requisitions/{id}/cancel` | Cancel an OPEN/SOURCED/CREDENTIALING requisition; the gap re-opens | SchedulerAdmin |
| GET | `/api/credentialing-cases` | List credentialing cases | SchedulerAdmin, ChiefOfStaff, Physician, CredentialingOfficer |
| GET | `/api/credentialing-cases/{id}` | Get a credentialing case | SchedulerAdmin, ChiefOfStaff, Physician, CredentialingOfficer |
| POST | `/api/credentialing-cases/{id}/complete-item` | Complete one checklist item; the fifth clears the case and auto-fills the gap | CredentialingOfficer |
| POST | `/api/credentialing-cases/{id}/fail` | Fail an active case; the requisition re-opens | CredentialingOfficer |
| POST | `/api/credentialing-cases/{id}/expire` | Expire an active case whose deadline has passed; the requisition re-opens | CredentialingOfficer |
| GET | `/api/pay-entries` | List pay entries | SchedulerAdmin, ChiefOfStaff, Physician, CredentialingOfficer |
| GET | `/api/pay-entries/{id}` | Get a pay entry | SchedulerAdmin, ChiefOfStaff, Physician, CredentialingOfficer |
| POST | `/api/_clock/set_current_utc` | Set the server logical clock | SchedulerAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in the narratives of §2 and §3; this table is the identifier-to-status reference.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_OWNERSHIP_VIOLATION` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_PROGRAM_NOT_FOUND` | 404 Not Found |
| `ERR_PHYSICIAN_NOT_FOUND` | 404 Not Found |
| `ERR_SLOT_NOT_FOUND` | 404 Not Found |
| `ERR_ASSIGNMENT_NOT_FOUND` | 404 Not Found |
| `ERR_SWAP_NOT_FOUND` | 404 Not Found |
| `ERR_WINDOW_NOT_FOUND` | 404 Not Found |
| `ERR_GAP_NOT_FOUND` | 404 Not Found |
| `ERR_REQUISITION_NOT_FOUND` | 404 Not Found |
| `ERR_CASE_NOT_FOUND` | 404 Not Found |
| `ERR_PAY_ENTRY_NOT_FOUND` | 404 Not Found |
| `ERR_PROGRAM_NOT_DRAFT` | 409 Conflict |
| `ERR_PROGRAM_NOT_GENERATED` | 409 Conflict |
| `ERR_PROGRAM_NOT_PUBLISHED` | 409 Conflict |
| `ERR_REGENERATE_HAS_PROGRESS` | 409 Conflict |
| `ERR_UNRESOLVED_ASSIGNMENTS_EXIST` | 409 Conflict |
| `ERR_PERIOD_NOT_ENDED` | 409 Conflict |
| `ERR_SLOT_NOT_OPEN` | 409 Conflict |
| `ERR_SLOT_WINDOW_PASSED` | 409 Conflict |
| `ERR_ASSIGNMENT_NOT_SCHEDULED` | 409 Conflict |
| `ERR_ASSIGNMENT_NOT_ACTIVATABLE` | 409 Conflict |
| `ERR_ASSIGNMENT_NOT_SERVABLE` | 409 Conflict |
| `ERR_ACTIVATION_REQUIRES_BACKUP_SLOT` | 409 Conflict |
| `ERR_SWAP_NOT_POSTED` | 409 Conflict |
| `ERR_SWAP_NOT_CLAIMED` | 409 Conflict |
| `ERR_SWAP_NOT_APPROVED` | 409 Conflict |
| `ERR_SWAP_ASSIGNMENT_NOT_SCHEDULED` | 409 Conflict |
| `ERR_WINDOW_NOT_REQUESTED` | 409 Conflict |
| `ERR_WINDOW_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_GAP_NOT_OPEN` | 409 Conflict |
| `ERR_REQUISITION_NOT_OPEN` | 409 Conflict |
| `ERR_REQUISITION_NOT_SOURCED` | 409 Conflict |
| `ERR_REQUISITION_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_CASE_NOT_ACTIVE` | 409 Conflict |
| `ERR_PHYSICIAN_INACTIVE` | 409 Conflict |
| `ERR_UNAVAILABILITY_CONFLICT` | 409 Conflict |
| `ERR_MOONLIGHT_CAP_EXCEEDED` | 409 Conflict |
| `ERR_WINDOW_COVERS_SERVED_ASSIGNMENT` | 409 Conflict |
| `ERR_PREREQUISITE_ITEM_INCOMPLETE` | 409 Conflict |
| `ERR_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_ASSIGNMENT_OVERLAP` | 409 Conflict |
| `ERR_SWAP_CUTOFF_VIOLATION` | 409 Conflict |
| `ERR_SERVE_BEFORE_WINDOW_END` | 409 Conflict |
| `ERR_ACTIVATION_WINDOW_CLOSED` | 409 Conflict |
| `ERR_CREDENTIALING_DEADLINE_PASSED` | 409 Conflict |
| `ERR_CREDENTIALING_NOT_EXPIRED` | 409 Conflict |
| `ERR_CREDENTIALING_INFEASIBLE` | 409 Conflict |
| `ERR_SPECIALTY_MISMATCH` | 409 Conflict |
| `ERR_MANUAL_ASSIGNMENT_STAFF_ONLY` | 409 Conflict |
| `ERR_SWAP_CLAIMANT_INELIGIBLE` | 409 Conflict |
| `ERR_CANDIDATE_NOT_LOCUM` | 409 Conflict |
| `ERR_SELF_SWAP` | 409 Conflict |
| `ERR_DUPLICATE_ACTIVE_SWAP` | 409 Conflict |
| `ERR_ITEM_ALREADY_COMPLETED` | 409 Conflict |
| `ERR_SWAP_EQUITY_BREACH` | 409 Conflict |
| `ERR_PAYROLL_BUDGET_EXCEEDED` | 402 Payment Required |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
