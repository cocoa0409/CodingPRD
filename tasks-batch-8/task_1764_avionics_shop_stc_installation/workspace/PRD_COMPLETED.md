# Avionics Shop STC API — Product Requirements Document

## 1. Introduction

A panel upgrade is the most coordination-heavy job a general-aviation shop takes on. The customer wants a firm quote and a firm return-to-service date; the shop must design the panel, wait on avionics with real vendor lead times, route the paperwork through either existing Supplemental Type Certificate data or a field approval, fabricate harnesses, hang the equipment, prove the installation on the ground and in the air, and re-issue the aircraft's weight and balance — all while the airframe sits in a hangar bay that other jobs are waiting for. Downtime estimates slip, parts arrive late, and labor bills look nothing like the flat-rate quote unless the shop tracks each of these threads explicitly.

This API is the operating system for that workflow at a Garmin-dealer avionics shop. It covers the full arc of an STC installation job: work-scope capture and panel-design approval by the aircraft owner, equipment procurement with lead-time tracking, the STC or field-approval documentation path, wiring and harness fabrication and installation hours, ground and flight test verification with a rework loop, aircraft downtime estimate versus actual with customer acknowledgement, weight-and-balance revision, and warranty plus software-subscription setup at closeout. All resources are served under the `/avionics` prefix.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that apply to every endpoint in the API.

### 2.1. User and Role-Based Access Control

Every request carries two identity headers: `X-User-ID`, identifying the actor, and `X-User-Role`, naming the actor's operational capacity. Four roles exist, spelled exactly: `ShopManager` (the shop's manager, owning quoting, procurement, scheduling, and closeout administration), `Technician` (the A&P mechanic performing harness fabrication and installation labor), `Inspector` (the IA-holder who verifies labor, records test results, decides regulatory packages, and accepts weight-and-balance revisions), and `Customer` (the aircraft owner). A request missing either header, or carrying a role outside this set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not permitted to perform the operation is rejected with `ERR_FORBIDDEN` (HTTP 403); the per-operation role assignments are enumerated in §4.

Identity semantics differ by role. When `X-User-Role` is `ShopManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the same is true for `Technician` and for `Inspector`. The server may record such identifiers — as `performed_by_user_id` when a technician completes a task, as `verified_by_user_id` when an inspector verifies one, as `decided_by_user_id` when an inspector records a regulatory decision — but it never compares them to any entity's `id` for ownership purposes. When `X-User-Role` is `Customer`, by contrast, `X-User-ID` is the `id` of the acting `Customer` entity, and ownership checks on any resource compare the resource's foreign-key chain — work order to aircraft to owning customer — against `X-User-ID`.

Two customer-privileged actions lean on that ownership rule: the customer's decision on a submitted panel design, and the customer's acknowledgement of a downtime overage. Both are rejected with `ERR_FORBIDDEN` when the acting customer's `id` is not the owner of the aircraft the target work order references. A separate duty rule applies to inspection: an inspector may never verify labor they performed themselves, and that comparison between the acting inspector's `X-User-ID` and the task's recorded `performed_by_user_id` is enforced at verification time with `ERR_SEGREGATION_OF_DUTIES`.

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

List endpoints paginate through two query parameters. The `limit` parameter caps how many items come back; it defaults to 10, and accepts values from a minimum of 1 to a maximum of 100. The `offset` parameter says how many items to skip and defaults to 0. A non-integer or out-of-range value for either parameter — a `limit` below 1 or above 100, or a negative `offset` — is rejected with `ERR_VALIDATION`.

Unless an endpoint states otherwise, every list returns its resources sorted by `created_at` in ascending order.

The `meta` object of a list response carries four pagination fields: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every resource in the system — customers, aircraft, work orders, panel designs, equipment orders, install tasks, test events, regulatory packages, and weight-and-balance revisions — carries a standard quartet of system-managed fields, and clients treat all four as read-only:

- `id` (string): a server-minted UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, set when the resource is created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every change to the resource's stored properties, including changes to server-computed properties.
- `version` (integer): a system-managed integer that increments with every modification to the resource.

A resource is created with `version` 1, and its `updated_at` initially equals its `created_at`.

### 2.5. The Shop's Logical Clock

Time inside this system comes from a single logical clock, not from the host's wall clock. At startup, before anyone has set it, the logical clock reads exactly 2026-08-01T00:00:00Z, and it never falls back to wall-clock time thereafter. Every timestamp the server assigns — `inducted_at`, `ordered_at`, `received_at`, `completed_at`, the computed `promised_date`, and the warranty and subscription expirations — is read from, or derived from, this clock.

A `ShopManager`-only test-driving capability sets the logical clock to a supplied `to_iso8601` instant and answers with the new `current_utc`. Lateness evaluation reads the same source: an equipment order's `is_late` compares its `received_at` — or, while the order is still unreceived, the current logical clock — against its `promised_date`.

### 2.6. Hangar Bays and Flight-Window Separation

Two scheduling disciplines run across the whole system, and both are enforced as half-open intervals: a window includes its start instant and excludes its end instant, so two windows that merely touch — one ending at exactly the instant the other begins — do not overlap.

Bay reservations come first. A work order occupies its `bay_code` for the window from `bay_window_start` to `bay_window_end`. Opening a work order conflicts with another non-terminal work order on the same bay when the new window starts before the existing window ends and ends after the existing window starts; such a conflict is rejected with `ERR_BAY_WINDOW_CONFLICT` (HTTP 409). Work orders that reach a terminal state — completed or cancelled — release their bay.

Flight separation comes second. Every flight test in `SCHEDULED` or `FAILED` status owns a buffered window that runs from 60 minutes before its `scheduled_start` to 60 minutes after its `scheduled_end`, again half-open. When a flight is first scheduled, and again whenever a failed flight is rescheduled, the new window must not intersect the buffered window of any other `SCHEDULED` or `FAILED` flight belonging to the same aircraft; a violation is rejected with `ERR_FLIGHT_WINDOW_CONFLICT` (HTTP 409), while a window that only touches a buffer's edge is acceptable. Ground tests carry no buffer.

### 2.7. Money, Weights, and Measurement Precision

Money moves in whole cents. Every price, subtotal, quote, and billed figure is an integer number of cents produced by decimal arithmetic, and every rounding the business rules call for is half-up, applied at exactly the step the rule names; aggregates sum already-rounded figures and are never re-rounded. Labor-hour aggregates such as `total_actual_labor_hours` keep one decimal.

Weights and balance figures follow the shop's datum conventions. Weights — `baseline_empty_weight_lb`, per-line `weight_lb`, `new_empty_weight_lb` — carry one decimal. Moments — `baseline_moment_lb_in`, `new_moment_lb_in` — carry one decimal. Arms — `baseline_arm_in`, `cg_min_arm_in`, `cg_max_arm_in`, per-line `arm_in`, `new_arm_in` — carry two decimals. All of these round half-up to their stated precision. Durations that must land on whole days, such as the downtime figures, count complete 24-hour periods and discard any partial day rather than rounding it.

### 2.8. Optimistic Concurrency on Design Revisions

Exactly one write in this API is guarded by optimistic concurrency control. Creating a panel-design revision requires the request to carry `expected_work_order_version`, the work-order `version` the client last observed. If `expected_work_order_version` does not match the work order's current `version` — as happens when the current version has advanced past the value the client last observed — the create is rejected with `ERR_STALE_VERSION` (HTTP 412), forcing the client to re-read the work order before authoring the next revision. The guard exists because creating a revision legitimately supersedes the previous non-terminal revision and itself advances the work order's `version`; a client holding a stale version must never silently supersede work it has not observed. No other endpoint accepts a version field.

### 2.9. Derived Counters, Roll-Ups, and Aircraft Availability

Four aggregates on the work order are server-maintained and are recomputed whenever an underlying child row mutates in a way that can change them — equipment-order creation, receipt, or cancellation; install-task creation, completion, verification, voiding, or the flight-failure revert (every recorded flight-test failure recomputes, even when no task reverts); and the work-order cancellation cascade — whether the mutation came from a direct action or from a cascade. Child mutations that cannot change any figure, such as marking an equipment order ordered or starting a task, trigger no recomputation and leave the work order untouched:

- `parts_pending_count` counts the work order's equipment orders in `PLANNED` or `ORDERED`.
- `tasks_unverified_count` counts its install tasks in `PLANNED`, `IN_PROGRESS`, or `COMPLETED`.
- `total_actual_labor_hours` sums `actual_hours` over its install tasks in `COMPLETED` or `VERIFIED`.
- `total_billed_labor_cents` sums `billed_labor_cents` over its install tasks in `VERIFIED` only.

`VOIDED` tasks and `CANCELLED` or `RECEIVED` orders contribute nothing to these figures. Each recomputation is itself a mutation of the work order and refreshes its `updated_at`.

Aircraft availability is likewise derived rather than set by clients: an aircraft reads `IN_SHOP` while any non-terminal work order references it and `AVAILABLE` otherwise. Opening a work order flips its aircraft from `AVAILABLE` to `IN_SHOP`; completing or cancelling that work order flips it back.

Version advancement on the work order follows an explicit rule. Every status transition of the work order — client-driven or cascade-driven — increments its `version` by exactly one, and so does each newly authored panel-design revision and each customer overage acknowledgement.

### 2.10. Resource Addressing and Existence Checks

Path identifiers are validated left to right: the first id in the path that does not correspond to an existing resource fails the request with `ERR_NOT_FOUND` (HTTP 404) before any later id is examined. References carried inside request bodies — the `customer_id` on aircraft registration, the `aircraft_id` on work-order creation, the `work_order_id` carried by every child resource — are checked the same way: a reference to a nonexistent target is answered with `ERR_NOT_FOUND`, not with a schema error.

### 2.11. Validation Order

When several checks could reject the same request, the server does not choose among them freely: checks run in the fixed order below, and the request fails with the first violation found.

Authentication comes first — missing or unknown identity headers draw `ERR_UNAUTHENTICATED`. Authorization follows — a role not permitted for the endpoint, or a customer acting on a job whose aircraft they do not own, draws `ERR_FORBIDDEN`. Third come request-body schema checks: required fields present, types valid, enum values in range, `quantity` at least 1, `unit_price_cents` greater than 0, `estimated_hours` greater than 0, `lead_time_days` zero or more, every time window ending after it begins, `removed_arm_in` present exactly when `removed_weight_lb` is greater than zero, and `stc_number` present exactly when `approval_path` is `STC`; the `stc_number` condition carries `ERR_STC_NUMBER_REQUIRED`, and the rest carry `ERR_VALIDATION`. Fourth is existence, per §2.10, with `ERR_NOT_FOUND`. Between existence and state validity sits the single optimistic-concurrency guard: on panel-design creation a mismatched `expected_work_order_version` is rejected with `ERR_STALE_VERSION` only once the target work order has been found to exist, and before any state check. Fifth is state validity with `ERR_INVALID_STATE`: the target entity must sit in a valid from-state for the requested transition, which also covers terminal lockdown and actions attempted on superseded designs.

Sixth come the safety and compliance gates, which keep their own internal order: segregation of duties on task verification (`ERR_SEGREGATION_OF_DUTIES`), then the ground-before-flight requirement on flight-test scheduling (`ERR_GROUND_TEST_REQUIRED`), then CG limits on weight-and-balance acceptance (`ERR_CG_OUT_OF_LIMITS`), and on work-order completion the trio of tests passed, regulatory approved, and weight-and-balance accepted in that sequence (`ERR_TESTS_NOT_PASSED`, then `ERR_REGULATORY_NOT_APPROVED`, then `ERR_WB_NOT_ACCEPTED`). Seventh are the temporal conflicts: bay-window overlap on work-order creation (`ERR_BAY_WINDOW_CONFLICT`), flight-window buffer conflicts on test-event scheduling and rescheduling (`ERR_FLIGHT_WINDOW_CONFLICT`), and the unacknowledged downtime overage on completion (`ERR_DOWNTIME_OVERAGE_UNACKED`). Eighth is cross-reference lineage: submitting a quote with no usable design (`ERR_NO_PANEL_DESIGN`) and raising a manual change order against a work order that is not yet approved (`ERR_WORK_ORDER_NOT_APPROVED`). Ninth are uniqueness and capacity rules: a duplicate tail number on aircraft registration (`ERR_DUPLICATE_TAIL_NUMBER`), a second open work order for one aircraft (`ERR_AIRCRAFT_BUSY`), a second regulatory package for one work order (`ERR_PACKAGE_ALREADY_EXISTS`), a reschedule beyond the third test attempt (`ERR_TEST_ATTEMPT_LIMIT`), induction while parts remain outstanding (`ERR_PARTS_PENDING`), and the two begin-testing gates (`ERR_NO_INSTALL_TASKS`, `ERR_TASKS_UNVERIFIED`). Tenth and last, evaluated only after everything else has passed, is the change-order budget on manual equipment-order creation (`ERR_BUDGET_EXCEEDED`).

## 3. Business Logic & Workflows

### 3.1. Opening a Job: Customers, Aircraft, and the Work Order

A job begins with the customer roster. A `ShopManager` registers a customer with a `name` and a `contact_email` — the address downtime updates flow to — and an optional `customer_kind` of `INDIVIDUAL`, `FLIGHT_SCHOOL`, or `FLEET_OPERATOR`, which defaults to `INDIVIDUAL` when omitted. The kind is not cosmetic: it selects the equipment discount tier applied when a quote is later computed.

Aircraft come next. Registering an aircraft requires the owning `customer_id`, a `tail_number`, the `make_model`, and a baseline weight-and-balance datum: `baseline_empty_weight_lb` to one decimal, `baseline_arm_in` to two decimals, and the forward and aft CG limits `cg_min_arm_in` and `cg_max_arm_in`. From these the server derives `baseline_moment_lb_in` as the product of the baseline empty weight and the baseline arm, rounded half-up to one decimal. Tail numbers are unique across all registered aircraft; a duplicate `tail_number` is refused with `ERR_DUPLICATE_TAIL_NUMBER`. A newly registered aircraft carries `status` `AVAILABLE`, and the aircraft roster can be listed and filtered by `customer_id`.

With an aircraft on file, a `ShopManager` opens a work order by supplying its `aircraft_id`, a free-text `scope_description`, the quoted `estimated_downtime_days` in whole days, the flat-rate `quoted_labor_hours`, and a bay reservation made of `bay_code`, `bay_window_start`, and `bay_window_end`, with the end required to be later than the start (`ERR_VALIDATION`). Two term fields may ride along at creation: `warranty_term_months` and `software_subscription_months`, each defaulting to 12 calendar months when omitted and otherwise accepted as any integer, with no further bounds enforced. Only one open work order per aircraft is tolerated — the aircraft must be `AVAILABLE` at creation, otherwise the open fails with `ERR_AIRCRAFT_BUSY` — and the bay window is reserved immediately, running the half-open overlap check of §2.6 against the other non-terminal work orders on the same `bay_code` and rejecting overlaps with `ERR_BAY_WINDOW_CONFLICT`.

Creation flips the aircraft from `AVAILABLE` to `IN_SHOP` automatically. The new work order starts in `DRAFT` with its derived counters at zero — `parts_pending_count`, `tasks_unverified_count`, `total_actual_labor_hours`, and `total_billed_labor_cents` — with `overage_acknowledged` false, and with `inducted_at`, `completed_at`, and `quoted_total_cents` still null. Work orders can be listed filtered by `aircraft_id`, by `status`, or by both.

### 3.2. Panel Design Revisions and the Quoting Cycle

Design work proceeds by revision. A `ShopManager` authors a panel design against a work order by supplying its `work_order_id`, free-text `layout_notes`, an `equipment_list`, and the concurrency token `expected_work_order_version` described in §2.8. Each line of the `equipment_list` carries a `part_number`, a `description`, a `quantity`, a `unit_price_cents`, a `weight_lb`, an `arm_in`, and a `lead_time_days`; the list may be empty for a labor-only job. Creation is accepted only while the work order is in `DRAFT` or `PENDING_APPROVAL` — once the customer has approved, the scope is locked and further revisions are rejected with `ERR_INVALID_STATE`.

Each new revision receives a `revision` number one greater than the count of revisions the work order already has, assigned in creation order starting from 1, and the server computes `total_added_weight_lb` as the sum over the equipment lines of each line's `quantity` times its `weight_lb`, kept to one decimal. Creating a revision automatically supersedes every earlier revision of the same work order still sitting in `DRAFT`, `SUBMITTED`, or `CHANGES_REQUESTED` — those move to `SUPERSEDED` — and advances the work order's `version`. An `APPROVED` design is terminal and is never superseded. Designs can be listed filtered by `work_order_id`, by `status`, or by both.

When the shop is ready for the customer to look, the `ShopManager` submits a `DRAFT` revision and it moves to `SUBMITTED`; this is allowed only while the parent work order is itself in `DRAFT` or `PENDING_APPROVAL`, with `ERR_INVALID_STATE` answering any other state.

Quoting is a separate, explicit act. Submitting the quote moves the work order from `DRAFT` to `PENDING_APPROVAL` and computes `quoted_total_cents`. The quote requires at least one design revision still in `DRAFT` or `SUBMITTED`; if every revision has been superseded or bounced back for changes, the attempt fails with `ERR_NO_PANEL_DESIGN`. The computation reads the highest-revision revision that has not been superseded. Its labor component is the work order's `quoted_labor_hours` times the shop rate of 14,500 cents per hour, rounded half-up to whole cents. Its equipment component sums each line's extended price — `quantity` times `unit_price_cents` — across the design, then applies a discount keyed to the owning customer's `customer_kind`: ten percent for `FLEET_OPERATOR`, five percent for `FLIGHT_SCHOOL`, and no discount for `INDIVIDUAL`. The discounted equipment figure is rounded half-up to whole cents, and `quoted_total_cents` is the labor component plus that rounded figure. The work order's `version` advances by one.

The decision belongs to the customer. Acting under the `Customer` role — with `X-User-ID` equal to the `id` of the customer that owns the work order's aircraft, otherwise `ERR_FORBIDDEN` — the owner records an `outcome` on a `SUBMITTED` design while the work order sits in `PENDING_APPROVAL` (`ERR_INVALID_STATE` in any other state). An `outcome` of `APPROVE` moves the design to `APPROVED` and cascades into the work order. When the approved design's `equipment_list` is empty, the work order advances from `PENDING_APPROVAL` to `APPROVED`. When the list is non-empty, the work order advances to `PARTS_PENDING` instead, and the server auto-creates one equipment order per equipment line, in line order, each in `PLANNED` with `source` `DESIGN_RELEASE`, each carrying `source_design_revision` equal to the approved `revision`, each assigned its `seq`, with `parts_pending_count` recomputed so that it lands exactly on the number of lines created. Either way the work order's `version` advances by one. An `outcome` of `REQUEST_CHANGES` moves the design to `CHANGES_REQUESTED` and leaves the work order in `PENDING_APPROVAL`; the shop answers by authoring a fresh revision, whose creation supersedes the rejected one.

### 3.3. Procurement, Lead Times, and Change-Order Budgets

Equipment orders move through `PLANNED`, then `ORDERED`, and finally `RECEIVED` or `CANCELLED`. Marking an order placed records `ordered_at` from the logical clock and computes `promised_date` as exactly `lead_time_days` full 24-hour days after that instant, preserving the time of day; both fields stay null until the order is marked ordered. Receiving the parts records `received_at` — likewise null until receipt — and resolves `is_late`: the order is late only when `received_at` falls strictly later than `promised_date`, and arrival exactly on the promised instant is on time. While an order remains unreceived, reads evaluate `is_late` against the current logical clock, and before the order has been marked ordered at all, `is_late` stays false. Both receipt and cancellation recompute the parent work order's `parts_pending_count`, and cancellation is available from `PLANNED` or `ORDERED`.

Beyond the design-release cascade, a `ShopManager` may raise a change order manually with `work_order_id`, `part_number`, `description`, a `quantity` of at least 1, a `unit_price_cents` greater than 0, and a `lead_time_days` of 0 or more; violations of those bounds are `ERR_VALIDATION`. Manual lines are accepted only while the work order is `APPROVED` or `PARTS_PENDING`; any other state draws `ERR_WORK_ORDER_NOT_APPROVED`. A manual line is stamped with `source` `MANUAL`, carries a null `source_design_revision`, receives the next `seq`, and starts in `PLANNED`. If the work order was `APPROVED`, adding the line cascades it to `PARTS_PENDING` and recomputes `parts_pending_count`; if it was already `PARTS_PENDING`, only the count moves.

Change orders answer to a budget. The committed parts spend of a work order is the sum of `quantity` times `unit_price_cents` over all of its equipment orders that are not `CANCELLED`, including the line being added. A manual line whose extended price would push that commitment beyond the greater of two bounds — 110 percent of the approved design's equipment subtotal, or a floor of 250,000 cents — is rejected with `ERR_BUDGET_EXCEEDED`. The approved design's subtotal is the same per-line extended-price summation used in quoting, so for a job approved with an empty equipment list the floor alone governs.

Every equipment order carries a `seq`, a per-work-order sequence number that increases with creation order so that cascade-created rows keep a stable order. The equipment-order list sorts by `created_at` ascending and then by `seq` ascending, and can be filtered by `work_order_id`, by `status`, or by both.

### 3.4. Induction, Shop Labor, and Verified Billing

Labor is planned as install tasks. A `ShopManager` adds a task with `work_order_id`, a `task_kind` of `HARNESS_FABRICATION`, `PANEL_ASSEMBLY`, or `INSTALLATION`, a `description`, and a positive `estimated_hours`. Tasks may be added whenever the work order is `APPROVED`, `PARTS_PENDING`, or `INSTALLATION` (`ERR_INVALID_STATE` otherwise) — harness and panel work routinely begins before the airframe is physically inducted. A new task starts in `PLANNED`, and the work order's `tasks_unverified_count` is recomputed. Tasks can be listed filtered by `work_order_id`, by `status`, or by both.

Induction is the moment the downtime clock starts. Beginning installation moves the work order from `APPROVED` or `PARTS_PENDING` to `INSTALLATION`, and it is refused while any equipment order is still `PLANNED` or `ORDERED` — that is, while `parts_pending_count` is above zero — with `ERR_PARTS_PENDING`. On induction the server stamps `inducted_at` from the logical clock and advances the work order's `version`.

A `Technician` starts a task, moving it from `PLANNED` to `IN_PROGRESS`, and later completes it by reporting `actual_hours` — accepted as any number, with no positivity bound — moving it to `COMPLETED`; both actions require the parent work order to be in `APPROVED`, `PARTS_PENDING`, or `INSTALLATION` (`ERR_INVALID_STATE`). Completion stamps `performed_by_user_id` with the acting technician's `X-User-ID` and recomputes the parent's `total_actual_labor_hours` and `tasks_unverified_count`; until that first completion lands, both `actual_hours` and `performed_by_user_id` are null, and `verified_by_user_id` stays null until an inspector verifies the task. When a task returns from rework and is completed again, the newly reported `actual_hours` replaces the prior figure rather than adding to it.

Verification belongs to an `Inspector`, and never to the hands that did the work: the acting inspector's `X-User-ID` must differ from the task's `performed_by_user_id`, or the verification is refused with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). A successful verification moves the task from `COMPLETED` to `VERIFIED`, records `verified_by_user_id`, computes `billed_labor_cents`, and recomputes the parent's `total_billed_labor_cents` and `tasks_unverified_count`.

Billing is tiered per task. The first 8 hours of a task's `actual_hours` bill as regular time, and any hours beyond 8 bill at one and a half times. The payable hours are multiplied by the shop rate of 14,500 cents per hour and by the task-kind multiplier — 1.0 for `HARNESS_FABRICATION`, 1.1 for `PANEL_ASSEMBLY`, and 1.25 for `INSTALLATION` — and the product is rounded half-up to whole cents. Rounding happens once, per task, at verify time; the work-order aggregate `total_billed_labor_cents` sums these per-task figures over `VERIFIED` tasks and is never re-rounded. This actual-variant billing deliberately differs from the estimated labor figure inside a quote, which is a flat `quoted_labor_hours` times the shop rate with no overtime tier and no task-kind multiplier, so identical hour counts produce different totals under the two variants.

A task that should never have been worked can be voided by a `ShopManager` from `PLANNED`, `IN_PROGRESS`, or `COMPLETED`, moving it to the terminal `VOIDED` state and recomputing the parent's derived fields; voiding a `COMPLETED` task removes its `actual_hours` from the work order's labor-hour sum. A `VERIFIED` task cannot be voided directly — it leaves `VERIFIED` only through the flight-failure rework loop described next.

### 3.5. Ground and Flight Testing

With the work installed, the `ShopManager` moves the work order into `TESTING`. The move is gated, and the gates are checked in order: first, a work order with nothing to test at all — no `VERIFIED` task and no unverified task outstanding (`tasks_unverified_count` zero, as when no task exists or every task is `VOIDED`) — is refused with `ERR_NO_INSTALL_TASKS`; then a work order with tasks still unverified — `tasks_unverified_count` above zero — is refused with `ERR_TASKS_UNVERIFIED`, whether or not another task is already `VERIFIED`. Only a work order with at least one `VERIFIED` task and none unverified passes both gates. The transition advances the work order's `version`.

Testing is scheduled as test events. A `ShopManager` schedules an event with `work_order_id`, a `test_kind` of `GROUND` or `FLIGHT`, and a window from `scheduled_start` to `scheduled_end`, the end strictly after the start (`ERR_VALIDATION`). Events can exist only while the work order is in `TESTING` (`ERR_INVALID_STATE`), and a new event starts `SCHEDULED` with `attempt` 1 and `result` `NONE`. Flight carries two extra gates: at least one `GROUND` event of the same work order must already be `PASSED` (`ERR_GROUND_TEST_REQUIRED`), and the new window must clear the 60-minute buffered separation rule of §2.6 against every other `SCHEDULED` or `FAILED` flight of the same aircraft (`ERR_FLIGHT_WINDOW_CONFLICT`). Test events can be listed filtered by `work_order_id`, by `test_kind`, or by both.

An `Inspector` records the outcome. A `result` of `PASS` moves the event from `SCHEDULED` to `PASSED`; a `result` of `FAIL` moves it to `FAILED`, and either recording requires the parent work order in `TESTING` (`ERR_INVALID_STATE`). A failed ground run is a bench matter: no cascade fires, and the event simply awaits reschedule. A failed flight check is heavier. Every install task of the same work order currently `VERIFIED` reverts to `IN_PROGRESS`; its `billed_labor_cents` and `verified_by_user_id` are cleared to null, and the parent's `total_billed_labor_cents` and `tasks_unverified_count` are recomputed. While unverified tasks remain after that revert, the work order itself regresses from `TESTING` back to `INSTALLATION` and its `version` advances; if no task reverted, the work order stays in `TESTING`. Reworked tasks are then completed again — their `actual_hours` replaced, not accumulated — and must be verified anew before the shop can return to testing.

A failed event may be rescheduled by a `ShopManager`, moving it from `FAILED` back to `SCHEDULED` with a fresh `scheduled_start` and `scheduled_end`; the parent work order's own state imposes no further gate, so a failed event may be rescheduled during the `INSTALLATION` rework loop as well as in `TESTING`; the reschedule increments `attempt` by one and resets `result` to `NONE`. Three attempts is the ceiling — the initial run plus two reschedules — so rescheduling is refused once `attempt` has reached 3 (`ERR_TEST_ATTEMPT_LIMIT`), and a rescheduled flight re-runs the buffered-window conflict check (`ERR_FLIGHT_WINDOW_CONFLICT`). Cancelling the work order cascades `SCHEDULED` and `FAILED` events to `CANCELLED`; `PASSED` events are terminal and stand.

### 3.6. Regulatory Documentation: STC Data and Field Approvals

Paperwork runs in parallel with the wrenches. A `ShopManager` opens the regulatory package with a `work_order_id` and an `approval_path` of `STC` — installation under existing Supplemental Type Certificate data — or `FIELD_APPROVAL` — direct FAA inspector approval. The `stc_number` is required exactly when the path is `STC`; a missing number on that path is rejected with `ERR_STC_NUMBER_REQUIRED` (HTTP 400). One package per work order is the rule, and a second attempt draws `ERR_PACKAGE_ALREADY_EXISTS`. The package may be opened any time from `PENDING_APPROVAL` through `TESTING` — that is, while the work order is `PENDING_APPROVAL`, `APPROVED`, `PARTS_PENDING`, `INSTALLATION`, or `TESTING` — but not earlier or later (`ERR_INVALID_STATE`). It begins in `DRAFT`, with `faa_tracking_number` null on the STC path and `decided_by_user_id` null until an approving decision lands — a rejection does not stamp it. Packages can be listed filtered by `work_order_id`.

Submission is path-dependent. Submitting an `STC` package moves it from `DRAFT` to `CONFORMITY_REVIEW`; submitting a `FIELD_APPROVAL` package moves it from `DRAFT` to `FAA_SUBMITTED` and mints an `faa_tracking_number` on that first submission, a number retained unchanged across any later resubmissions. Submitting a package against the wrong track — a field-approval package into conformity review, or an STC package to the FAA — is rejected with `ERR_INVALID_STATE`. Neither submission nor decision-recording re-checks the parent work order's state; only the package's own state gates them.

An `Inspector` then records the `decision`. A `decision` of `APPROVED` moves the package from `CONFORMITY_REVIEW` or `FAA_SUBMITTED` into the terminal `APPROVED` state and stamps `decided_by_user_id` with the acting inspector's `X-User-ID`. A `decision` of `REJECTED` sends the package back to `DRAFT` — the conformity-rejection loop for STC data, the FAA-rejection loop for field approvals — where the data is corrected in place and resubmitted through the same path-dependent submission.

### 3.7. Weight and Balance Revisions

Every avionics job disturbs the aircraft's weight and balance, and closeout requires an accepted revision. A `ShopManager` computes a revision while the work order is in `INSTALLATION` or `TESTING` (`ERR_INVALID_STATE` otherwise), supplying `work_order_id`, a `method` of `INCREMENTAL` or `FULL_REWEIGH`, optional `added_items` — manual lines each carrying a `description`, a `weight_lb`, and an `arm_in`, defaulting to an empty list — and an optional `removed_weight_lb` that defaults to 0 and must be zero or more (`ERR_VALIDATION`). The `removed_arm_in` is required exactly when `removed_weight_lb` is greater than zero; omitting it when weight was removed, or supplying it when nothing was removed, is a request-body failure (`ERR_VALIDATION`). A fresh revision lands in `COMPUTED` with its results calculated, and revisions can be listed filtered by `work_order_id`.

The two methods differ in what they build on and — pinned precisely — in where rounding happens. An `INCREMENTAL` revision builds on the latest `ACCEPTED` revision of the same work order, falling back to the aircraft baseline when none has been accepted, and considers only the manual `added_items`; it never re-reads design lines. Under this method each added line's moment — its `weight_lb` times its `arm_in` — is rounded half-up to one decimal before any summing, and those rounded moments are summed; the removed moment — `removed_weight_lb` times `removed_arm_in` — is likewise rounded half-up to one decimal; `new_moment_lb_in` is then the base moment plus the summed added moments minus the rounded removed moment, with that result itself rounded half-up to one decimal. A `FULL_REWEIGH` revision always builds on the aircraft baseline — `baseline_empty_weight_lb` and `baseline_moment_lb_in` — ignoring any prior revisions, and folds in every line of the work order's `APPROVED` panel design, each line contributing its `quantity` times its `weight_lb` at its `arm_in`, alongside the manual lines. Under this method the line moments are summed unrounded, and `new_moment_lb_in` is the base moment plus that raw sum minus the raw removed-moment product, rounded half-up to one decimal exactly once. Identical inputs can therefore yield moments a tenth of a pound-inch apart between the two methods; the rounding order is part of the specification, not an implementation choice.

Weight is common to both methods: `new_empty_weight_lb` is the base weight plus the added lines' weights — design lines counted with their quantities — minus `removed_weight_lb`, rounded half-up to one decimal. The new arm `new_arm_in` is `new_moment_lb_in` divided by `new_empty_weight_lb`, rounded half-up to two decimals — a new weight of exactly zero yields an arm of 0.00. And `cg_within_limits` is true exactly when `new_arm_in` lies between the aircraft's `cg_min_arm_in` and `cg_max_arm_in`, inclusive on both ends.

Acceptance belongs to an `Inspector` and requires two things: the parent work order in `INSTALLATION` or `TESTING` (`ERR_INVALID_STATE`), and `cg_within_limits` true — an out-of-envelope revision is refused with `ERR_CG_OUT_OF_LIMITS` (HTTP 422). Accepting moves the revision from `COMPUTED` to `ACCEPTED` and automatically supersedes whichever revision of the same work order was previously `ACCEPTED`, moving it to `SUPERSEDED`.

### 3.8. Completion, Downtime Accounting, and Cancellation

Completion is the most heavily gated transition in the system, and its gates fire in a fixed order. First, testing: at least one `GROUND` event and at least one `FLIGHT` event of the work order must be `PASSED`, otherwise `ERR_TESTS_NOT_PASSED`. Second, paperwork: a regulatory package in `APPROVED` must exist for the work order, otherwise `ERR_REGULATORY_NOT_APPROVED`. Third, weight and balance: a revision in `ACCEPTED` must exist, otherwise `ERR_WB_NOT_ACCEPTED`. Fourth, the downtime gate: when the job has run five or more days beyond the estimate — measured as the complete 24-hour periods elapsed between `inducted_at` and the current logical clock, minus `estimated_downtime_days` — `overage_acknowledged` must be true, and an unacknowledged overage of that size rejects completion with `ERR_DOWNTIME_OVERAGE_UNACKED`.

The acknowledgement itself belongs to the customer. Acting under the `Customer` role with `X-User-ID` equal to the owning customer's `id` (`ERR_FORBIDDEN` otherwise), the owner records the acknowledgement, which sets `overage_acknowledged` to true and advances the work order's `version` by one. The acknowledgement is accepted from any non-terminal work-order state; on a `COMPLETED` or `CANCELLED` work order it is refused with `ERR_INVALID_STATE`.

Completing moves the work order from `TESTING` to the terminal `COMPLETED` state. Until this transition, `actual_downtime_days`, `downtime_overage_days`, `warranty_expires_at`, and `subscription_expires_at` all remain null. The server stamps `completed_at` from the logical clock and settles the downtime ledger: `actual_downtime_days` counts the complete 24-hour periods between `inducted_at` and `completed_at`, discarding any partial final day, and `downtime_overage_days` is that actual figure minus `estimated_downtime_days`. Warranty and subscription clocks start at completion: `warranty_expires_at` is `completed_at` shifted forward by `warranty_term_months` calendar months, and `subscription_expires_at` is `completed_at` shifted forward by `software_subscription_months` calendar months; in both cases, when the target month lacks the completion's day-of-month, the date clamps to that month's last day. Completion also returns the aircraft from `IN_SHOP` to `AVAILABLE` and advances the work order's `version` by one.

Cancellation is the other exit. A `ShopManager` may cancel from any non-terminal state — `DRAFT`, `PENDING_APPROVAL`, `APPROVED`, `PARTS_PENDING`, `INSTALLATION`, or `TESTING` — moving the work order to the terminal `CANCELLED`. The cancel cascade resolves every child of the work order: equipment orders in `PLANNED` or `ORDERED` move to `CANCELLED`; install tasks in `PLANNED`, `IN_PROGRESS`, or `COMPLETED` move to `VOIDED`, while a `VERIFIED` task is left untouched; test events in `SCHEDULED` or `FAILED` move to `CANCELLED`; and panel designs in `DRAFT`, `SUBMITTED`, or `CHANGES_REQUESTED` move to `SUPERSEDED`. The derived counters `parts_pending_count` and `tasks_unverified_count` are recomputed, the aircraft returns from `IN_SHOP` to `AVAILABLE`, and the work order's `version` advances by one. Work orders already `COMPLETED` or `CANCELLED` accept no further actions — terminal lockdown is reported as `ERR_INVALID_STATE`.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return a `201 Created` status code. Operations that modify an existing resource — including every state-transition action — return a `200 OK` status code. The request and response shapes of each endpoint are defined by the narratives of §2 and §3; this table is the map, not the specification.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server's logical clock | ShopManager |
| POST | `/avionics/customers` | Register a customer | ShopManager |
| GET | `/avionics/customers/{customerId}` | Get a customer by id | Any |
| POST | `/avionics/aircraft` | Register an aircraft for a customer | ShopManager |
| GET | `/avionics/aircraft/{aircraftId}` | Get an aircraft by id | Any |
| GET | `/avionics/aircraft` | List aircraft, optionally filtered by customer | Any |
| POST | `/avionics/work-orders` | Open a work order (bay window reserved at creation) | ShopManager |
| GET | `/avionics/work-orders/{workOrderId}` | Get a work order by id | Any |
| GET | `/avionics/work-orders` | List work orders, optionally filtered by aircraft and/or status | Any |
| POST | `/avionics/work-orders/{workOrderId}/submit-quote` | Submit quote to customer; computes the quoted total from the latest design | ShopManager |
| POST | `/avionics/work-orders/{workOrderId}/begin-installation` | Induct the aircraft and start installation; requires all parts received or cancelled | ShopManager |
| POST | `/avionics/work-orders/{workOrderId}/begin-testing` | Move to testing; requires all tasks verified | ShopManager |
| POST | `/avionics/work-orders/{workOrderId}/complete` | Complete the work order after all closeout gates; computes downtime and warranty dates | ShopManager |
| POST | `/avionics/work-orders/{workOrderId}/cancel` | Cancel a non-terminal work order; cascades to children | ShopManager |
| POST | `/avionics/work-orders/{workOrderId}/acknowledge-overage` | Customer acknowledges the job may exceed the estimated downtime | Customer |
| POST | `/avionics/panel-designs` | Create a panel design revision (OCC-guarded; supersedes the prior non-terminal revision) | ShopManager |
| GET | `/avionics/panel-designs/{panelDesignId}` | Get a panel design by id | Any |
| GET | `/avionics/panel-designs` | List panel designs, optionally filtered by work order and/or status | Any |
| POST | `/avionics/panel-designs/{panelDesignId}/submit` | Submit a design for customer review | ShopManager |
| POST | `/avionics/panel-designs/{panelDesignId}/decide` | Customer decision on a submitted design | Customer |
| POST | `/avionics/equipment-orders` | Manually add a change-order equipment line | ShopManager |
| GET | `/avionics/equipment-orders/{equipmentOrderId}` | Get an equipment order by id | Any |
| GET | `/avionics/equipment-orders` | List equipment orders, optionally filtered by work order and/or status | Any |
| POST | `/avionics/equipment-orders/{equipmentOrderId}/mark-ordered` | Mark the order placed with the vendor | ShopManager |
| POST | `/avionics/equipment-orders/{equipmentOrderId}/receive` | Receive the parts | ShopManager |
| POST | `/avionics/equipment-orders/{equipmentOrderId}/cancel` | Cancel an un-received order | ShopManager |
| POST | `/avionics/install-tasks` | Add a labor task (harness fabrication, panel assembly, or installation) | ShopManager |
| GET | `/avionics/install-tasks/{installTaskId}` | Get an install task by id | Any |
| GET | `/avionics/install-tasks` | List install tasks, optionally filtered by work order and/or status | Any |
| POST | `/avionics/install-tasks/{installTaskId}/start` | Technician starts the task | Technician |
| POST | `/avionics/install-tasks/{installTaskId}/complete` | Technician records actual hours and completes the task | Technician |
| POST | `/avionics/install-tasks/{installTaskId}/verify` | Inspector verifies completed work (may not be the performer) | Inspector |
| POST | `/avionics/install-tasks/{installTaskId}/void` | Void a non-verified task (compensating action) | ShopManager |
| POST | `/avionics/test-events` | Schedule a ground or flight test | ShopManager |
| GET | `/avionics/test-events/{testEventId}` | Get a test event by id | Any |
| GET | `/avionics/test-events` | List test events, optionally filtered by work order and/or kind | Any |
| POST | `/avionics/test-events/{testEventId}/record-result` | Inspector records PASS/FAIL | Inspector |
| POST | `/avionics/test-events/{testEventId}/reschedule` | Reschedule a failed test (retest), up to 3 attempts | ShopManager |
| POST | `/avionics/regulatory-packages` | Create the STC or field-approval documentation package (one per work order) | ShopManager |
| GET | `/avionics/regulatory-packages/{regulatoryPackageId}` | Get a regulatory package by id | Any |
| GET | `/avionics/regulatory-packages` | List regulatory packages, optionally filtered by work order | Any |
| POST | `/avionics/regulatory-packages/{regulatoryPackageId}/submit` | Submit package: STC to conformity review, FIELD_APPROVAL to the FAA | ShopManager |
| POST | `/avionics/regulatory-packages/{regulatoryPackageId}/record-decision` | Inspector records APPROVED/REJECTED; rejection loops back to draft | Inspector |
| POST | `/avionics/weight-balance-revisions` | Compute a weight & balance revision (INCREMENTAL or FULL_REWEIGH) | ShopManager |
| GET | `/avionics/weight-balance-revisions/{weightBalanceRevisionId}` | Get a W&B revision by id | Any |
| GET | `/avionics/weight-balance-revisions` | List W&B revisions, optionally filtered by work order | Any |
| POST | `/avionics/weight-balance-revisions/{weightBalanceRevisionId}/accept` | Inspector accepts a W&B revision within CG limits; supersedes the prior accepted revision | Inspector |

## 5. Error Code Catalogue

The catalogue below enumerates every error identifier and its HTTP status. The conditions that trigger each error are defined in the narratives of §2 and §3, not here.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_VALIDATION` | 400 Bad Request |
| `ERR_STC_NUMBER_REQUIRED` | 400 Bad Request |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_GROUND_TEST_REQUIRED` | 409 Conflict |
| `ERR_CG_OUT_OF_LIMITS` | 422 Unprocessable Entity |
| `ERR_TESTS_NOT_PASSED` | 409 Conflict |
| `ERR_REGULATORY_NOT_APPROVED` | 409 Conflict |
| `ERR_WB_NOT_ACCEPTED` | 409 Conflict |
| `ERR_BAY_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_FLIGHT_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_DOWNTIME_OVERAGE_UNACKED` | 409 Conflict |
| `ERR_NO_PANEL_DESIGN` | 409 Conflict |
| `ERR_WORK_ORDER_NOT_APPROVED` | 409 Conflict |
| `ERR_DUPLICATE_TAIL_NUMBER` | 409 Conflict |
| `ERR_AIRCRAFT_BUSY` | 409 Conflict |
| `ERR_PACKAGE_ALREADY_EXISTS` | 409 Conflict |
| `ERR_TEST_ATTEMPT_LIMIT` | 409 Conflict |
| `ERR_PARTS_PENDING` | 409 Conflict |
| `ERR_TASKS_UNVERIFIED` | 409 Conflict |
| `ERR_NO_INSTALL_TASKS` | 409 Conflict |
| `ERR_BUDGET_EXCEEDED` | 409 Conflict |
