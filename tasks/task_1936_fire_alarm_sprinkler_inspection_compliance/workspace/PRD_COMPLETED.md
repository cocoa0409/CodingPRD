# Fire Protection Compliance API — Product Requirements Document

## 1. Introduction

Fire protection service contractors operate under continuous regulatory scrutiny: every alarm panel, sprinkler riser, backflow preventer, and fire pump they maintain carries code-mandated inspection frequencies, every impairment carries a notification deadline to the authority having jurisdiction, and every deficiency carries a correction clock. Authorities, in turn, must verify contractor licensing, adjudicate inspection reports, assess false-alarm fees, and police unpermitted modification work — all against a shared, auditable record. The Fire Protection Compliance API is the system of record for this relationship between a fire marshal's office and the licensed contractors working in its jurisdiction.

This document specifies the API's behavior end to end: contractor registration and licensing posture, property and system inventories with per-device inspection frequencies, annual inspection plans and their prorated fees, field execution of inspection events, deficiency correction loops with segregation of duties, impairment notification windows, marshal-portal report adjudication, specialty testing for backflow assemblies and fire pumps, false-alarm fee schedules, and modification permits with tiered fee computation. A server-maintained logical clock drives scheduled sweeps — license expiry, permit expiry, plan lapse, late-fee accrual, and impairment escalation — so that compliance posture is always a deterministic function of recorded history and the current logical date.

---

## 2. Global Specifications & System-Wide Principles

This section defines the cross-cutting contracts that apply uniformly to every endpoint. Domain workflows in §3 assume everything stated here.

### 2.1. User and Role-Based Access Control

Every request carries two mandatory HTTP headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming their operational capacity. The system recognizes exactly three roles, spelled precisely as follows: `FireMarshal`, `ContractorAdmin`, and `Technician`. A request missing either header, or presenting an `X-User-Role` value outside this declared set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not on the endpoint's authorized list is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The meaning of `X-User-ID` depends on the role presented:

- When `X-User-Role` is `FireMarshal`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example, as the verifying or attesting actor on a deficiency for segregation-of-duties comparison — but never compares it to any entity's `id`.
- When `X-User-Role` is `ContractorAdmin`, `X-User-ID` is the `id` of the acting Contractor; ownership checks on any resource that references a Contractor compare the resource's foreign-key field to `X-User-ID`.
- When `X-User-Role` is `Technician`, `X-User-ID` is the `id` of the acting Technician; assignment checks on an inspection event compare the event's `lead_technician_id` to `X-User-ID`.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned: it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0. A `limit` outside the range 1–100, a negative `offset`, or a non-integer value for either parameter is rejected with `ERR_INVALID_REQUEST`. All list endpoints return resources sorted by `created_at` in ascending order unless otherwise specified; records sharing the same `created_at` are ordered by insertion, earlier-created first. List responses include `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Resource Identity and Common Fields

Every resource in this API carries a uniform set of system-managed fields. The `id` is a server-minted UUID with no type prefix. `created_at` is an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created. `updated_at` follows the same format and refreshes on every mutation. `version` is an integer that starts at 1 on creation and increments by one on every mutation of that resource, including mutations driven by cascades or automatic system transitions. When a transition's side effects refresh a parent or sibling resource, that resource's `updated_at` is refreshed and its `version` incremented as well, so observers can always detect indirect mutation.

### 2.5. The Logical Clock and the Daily Sweep

The server maintains a logical clock rather than reading wall-clock time. At startup, the logical clock reads exactly `2026-08-01T00:00:00Z`; before any clock-setting call, this default is what the system treats as "now", and the clock never falls back to wall-clock. A `FireMarshal` may set the clock by supplying a `to_iso8601` instant — the new instant may be earlier or later than the current reading, and no monotonicity is enforced; the response echoes the new time as `current_utc`.

Setting the clock runs the daily-sweep logic for the new date. The sweep performs five jobs: it expires license records whose expiry date has passed, it expires issued permits whose validity window has elapsed without work commencing, it lapses inspection plans whose plan year has ended unfulfilled, it accrues deficiency late fees for deficiencies still open past their correction deadline, and it promotes long-open impairments to an out-of-service system condition. The monthly compounding of unpaid backflow-test balances is likewise evaluated through this sweep machinery. All date comparisons in the system — deadlines, due dates, windows, expiry — are evaluated against this logical clock.

### 2.6. Request Validation Pipeline and Error Precedence

Every request is validated in a fixed priority order, and the first failing rule determines the error returned. The order is:

1. **Authentication** — the `X-User-Role` header must be present and name a declared role, and `X-User-ID` must be present; failure yields `ERR_UNAUTHENTICATED`.
2. **Authorization** — the role must be permitted on the endpoint per the endpoint table; failure yields `ERR_UNAUTHORIZED`.
3. **Path existence** — every identifier in the URL path must exist, validated left to right; the first missing identifier yields `ERR_NOT_FOUND`.
4. **Body reference existence** — every foreign-key-valued body field must reference an existing entity; failure yields `ERR_REFERENCE_NOT_FOUND`.
5. **Transition legality** — the target resource must be in a state from which the requested transition exists; failure yields `ERR_INVALID_STATE`. Terminal-state lockdown and repeated actions also fail here.
6. **Parent-scope state gates** — all writes to a contractor's child resources require the contractor to be `ACTIVE` and, where applicable, the parent property to be `ACTIVE`, and any posture gate on the transition must pass; failure yields `ERR_CONTRACTOR_POSTURE_BLOCKED`.
7. **License validity** — on inspection-event start and on backflow and fire-pump test creation, the acting or named technician must hold an `ACTIVE` license of the required class whose expiry is strictly after the relevant date; failure yields `ERR_LICENSE_NOT_VALID`.
8. **System impairment gates** — operations requiring a normal system (permit issuance) or forbidding an out-of-service system (event start) are evaluated here, yielding `ERR_SYSTEM_IMPAIRED` or `ERR_SYSTEM_OUT_OF_SERVICE` respectively.
9. **Critical-waiver bar** — a critical deficiency is never waivable; failure yields `ERR_CRITICAL_NOT_WAIVABLE`.
10. **Date-range sanity** — every end must be strictly after its start: `expires_on` strictly after `issued_on`, `scheduled_end` strictly after `scheduled_start`, `planned_end` strictly after `planned_start`; failure yields `ERR_INVALID_DATE_RANGE`.
11. **Impairment overlap and re-certification buffer** — a new `PLANNED` impairment on the same system must not overlap another non-closed impairment's window and must respect the four-hour re-certification buffer; failure yields `ERR_IMPAIRMENT_OVERLAP`.
12. **Technician aggregate capacity** — a lead technician may not be assigned a fourth overlapping engagement; failure yields `ERR_TECHNICIAN_CAPACITY`.
13. **Uniqueness** — contractor license numbers, device serials within a system, and plan years within a property must be unique; failure yields `ERR_DUPLICATE_CONSTRAINT`.
14. **Enum membership** — every enum field value must lie in its declared set; failure yields `ERR_INVALID_ENUM`.
15. **Cross-aggregate integrity** — an event's system must belong to its plan's property, a deficiency's device must belong to its event's system, a pump test's coordinated event must cover the same system, and specialty-test system categories must match; failure yields `ERR_CROSS_REFERENCE_MISMATCH`.
16. **Open-item blockers** — archive, deactivation, decommission, replacement, and removal are blocked by listed open children; failure yields `ERR_OPEN_ITEMS_BLOCK`.
17. **Optimistic concurrency** — the expected-version field on plan creation and permit creation must equal the parent's current `version`; failure yields `ERR_STALE_VERSION`.
18. **Request shape** — all required body fields must be present with correct scalar types; failure yields `ERR_INVALID_REQUEST`.
19. **Segregation of duties** — the marshal verifying a deficiency correction must differ from the actor who attested it; failure yields `ERR_SEGREGATION_OF_DUTIES`.
20. **Extension eligibility** — deadline extension applies only to an open, noncritical deficiency that has never been extended; failure yields `ERR_DEFICIENCY_NOT_EXTENSIBLE`.

Two rules fire where the request body is parsed rather than strictly at their list positions: request shape (rule 18) is validated field-by-field as each endpoint reads its body, and enum membership (rule 14) is validated at the moment each enum field is read — so a shape or enum failure surfaces at the point the offending field is consumed, which may precede business rules listed before it. Endpoints that read no request body perform no rule-18 check at all.

### 2.7. Nested Paths and Cross-Aggregate Reference Integrity

For endpoints whose path contains multiple resource identifiers, the server validates path identifiers sequentially from left to right and rejects with `ERR_NOT_FOUND` at the first identifier that does not correspond to an existing resource, before any business rule runs. Foreign keys supplied in request bodies are existence-checked per rule 4 above, and their cross-aggregate consistency is checked per rule 15: the referenced entity must not merely exist — it must belong to the aggregate implied by the path. A device referenced when recording a deficiency must live in the system under inspection; a system referenced when scheduling an event must sit on the property the plan covers; a specialty test's system must be of the category the test type requires. Mismatches of this kind are reported as `ERR_CROSS_REFERENCE_MISMATCH`; the more specific aliases `ERR_SYSTEM_CATEGORY_MISMATCH` (a backflow test against a non-backflow system, or a fire-pump test against a non-pump system) and `ERR_DEVICE_REPLACEMENT_MISMATCH` (a replacement pointer that leaves the system, targets a non-in-service device, or self-references) belong to this same error class.

### 2.8. Optimistic Concurrency Control

Two creation endpoints carry an optimistic-concurrency contract, and only these two take an expected-version field.

Creating an annual inspection plan against a property requires the request to carry `expected_property_version`, holding the property's `version` as last observed by the client. If the property's current `version` differs — because another writer has mutated the property since the client last read it — the creation is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from building a plan on a property state it has not observed.

Creating a modification permit against a protected system requires `expected_system_version`, holding the system's `version` as last observed. A mismatch with the system's current `version` is likewise rejected with `ERR_STALE_VERSION` (HTTP 412). No other endpoint accepts a version field.

### 2.9. Compliance Scoring and Contractor Posture

Each contractor carries a `compliance_score`, an integer that starts at 1000 at registration and never falls below 0, and a derived `posture` that gates what the contractor's organization may do. The score is recomputed whenever any contributing fact changes — on every state transition whose side effects cite it, on the daily sweep, and on license expiry or revocation.

The **provisional** score — the variant persisted on the contractor and used by listings and posture gating — starts from 1000 and subtracts, for every entity whose ownership chain reaches the contractor:

- 40 for each `OPEN` `CRITICAL` deficiency whose `correction_deadline` has passed, and 10 for each `OPEN` `NONCRITICAL` deficiency past its deadline;
- 25 for each marshal report in `SUBMITTED` whose `is_late` is true;
- 60 for each impairment in `NOTIFIED`, `RESTORED`, or `CLOSED` whose `notification_late` is true;
- 15 for each false-alarm case in `ASSESSED` or `PAID` whose `cause_code` is `NEGLIGENCE`;
- 30 for each backflow test or fire-pump test in `FAILED_OPEN`;
- 75 for each inspection plan in `LAPSED`;
- 20 for each inspection event in `NO_ACCESS`;
- 5 for each deficiency in `WAIVED`;
- 100 for each modification permit in `FINED`.

The provisional score is the base formula exactly — no bonuses and no license deduction — floored at 0.

The **audited** score is computed on demand through a `FireMarshal`-only audit capability and is not persisted; the response carries both `audited_score` and `provisional_score`. The audited variant takes the provisional base, adds an on-time bonus of 2 points per inspection event completed on or after the date ninety days before the audit date (through the audit date inclusive) whose completion was on time, with the bonus capped at 50 points total, and subtracts 100 points if any technician of the contractor holds a license record in `EXPIRED` or `REVOKED` at audit time. The result is again floored at 0.

Posture derivation runs after every score recompute and after every deficiency opens or closes. Let the open-overdue-critical count be the number of the contractor's `CRITICAL` deficiencies that are `OPEN` and past their `correction_deadline`. The contractor is `SUSPENDED` when the score is below 600 or the open-overdue-critical count is at least 3; otherwise `PROBATION` when the score is below 850 or that count is at least 1; otherwise `GOOD_STANDING`. Posture gates child operations as specified per transition: plan publication and permit issuance require `GOOD_STANDING`, while event starts and report submissions require anything other than `SUSPENDED`. A `DEACTIVATED` contractor rejects all child writes. These gate failures surface as `ERR_CONTRACTOR_POSTURE_BLOCKED`.

### 2.10. Money, Dates, and Rounding Conventions

All monetary amounts are integer cents — `provisional_fee_cents`, `final_fee_cents`, `late_fee_cents`, `fee_cents`, `unpaid_balance_cents`, `project_valuation_cents`, and `permit_fee_cents` among them. Where a computation produces fractional cents, rounding is round-half-up to whole cents; each calculation in §3 states exactly where that rounding is applied, and several calculations deliberately round per line item or per compounding step rather than at the end — order matters and is specified per rule. Date arithmetic on inspection due dates uses calendar months with month-end clamping: adding one calendar month to January 31 yields February 28 (or 29 in a leap year). Datetime fields are ISO 8601; date-only fields carry no time component.

---

## 3. Business Logic & Workflows

### 3.1. Contractor Registration, Technicians, and Licensing

A `FireMarshal` onboards a fire protection service contractor by registering its `legal_name` and `state_license_no`. The license number is unique across all contractors; a conflicting registration is rejected with `ERR_DUPLICATE_CONSTRAINT` (carrying the specialized alias `ERR_DUPLICATE_LICENSE_NO`). A new contractor starts with `compliance_score` 1000 and `posture` `GOOD_STANDING`, and its `status` is `ACTIVE`. Contractors may be listed with an optional `posture` filter alongside the standard `limit` and `offset` parameters.

A `ContractorAdmin` staffs the firm by adding technicians with a `full_name` and a NICET certification `nicet_level` of `I`, `II`, `III`, or `IV`. Each technician belongs to exactly one contractor, recorded as `contractor_id`, and starts `ACTIVE`. A technician whose `status` has become `INACTIVE` may not be newly assigned as an inspection event's lead — scheduling one is rejected with `ERR_INVALID_STATE`; an inactive technician may still be named as a specialty test's tester, where only license validity gates.

Each technician's trade qualifications live in license records, each record bound to its owner through `technician_id`. Recording a license takes a `license_class` — one of `ALARM`, `SPRINKLER`, `BACKFLOW`, or `PUMP` — together with `issued_on` and `expires_on` dates; the expiry must be strictly after the issue date, failing which the request is rejected with `ERR_INVALID_DATE_RANGE`. A license record starts `ACTIVE`. When the logical date passes a record's `expires_on`, the daily sweep moves the record to `EXPIRED`, refreshes the owning technician's `updated_at`, increments the technician's `version`, and triggers a compliance-score recompute for the contractor. A `FireMarshal` may also revoke an `ACTIVE` license outright, moving it to `REVOKED` and triggering the same contractor-level recompute. Both terminal states, `EXPIRED` and `REVOKED`, feed the audited score's 100-point license deduction.

Deactivating a technician — a `ContractorAdmin` action — requires the technician to be `ACTIVE` and to have no inspection event assigned to them in `SCHEDULED` or `IN_PROGRESS`; open engagements block the action with `ERR_TECHNICIAN_HAS_OPEN_EVENTS`, an alias of the `ERR_OPEN_ITEMS_BLOCK` class. On deactivation the technician becomes `INACTIVE`, any of the technician's `ACTIVE` license records whose `expires_on` has already passed are swept to `EXPIRED`, and the technician's `updated_at` and `version` advance.

Deactivating an entire contractor is reserved to the `FireMarshal`. The contractor must be `ACTIVE`, and no inspection event in `SCHEDULED` or `IN_PROGRESS` may exist under any plan of any property of the contractor — otherwise the request fails with `ERR_OPEN_EVENTS_BLOCK_DEACTIVATION`, another `ERR_OPEN_ITEMS_BLOCK`-class alias. Deactivation cascades: every technician of the contractor becomes `INACTIVE`; every `OPEN` impairment on systems of the contractor's properties moves to `CLOSED` with `restored_at` stamped at deactivation time; every `DRAFT` marshal report on the contractor's events is deleted from the workflow while remaining queryable with its status unchanged. The contractor's own `updated_at` and `version` advance. From that point, the `DEACTIVATED` status rejects all child writes as `ERR_CONTRACTOR_POSTURE_BLOCKED`.

### 3.2. Property and System Inventory: Devices, Frequencies, and Due Dates

A `ContractorAdmin` registers each serviced property with its `contractor_id` of record, an `address_line`, an `occupancy_class` — one of `ASSEMBLY`, `BUSINESS`, `EDUCATIONAL`, `MERCANTILE`, `RESIDENTIAL`, or `STORAGE`, which drives false-alarm fee schedule variant selection — and a `jurisdiction_code`, the authority-having-jurisdiction code that determines marshal-portal receipt routing. Properties start `ACTIVE` and may be listed filtered by `contractor_id` or `occupancy_class`.

Beneath a property sit its protected systems, each one recording its containing property as `property_id`. Registering a system takes a `system_category` — `FIRE_ALARM`, `SPRINKLER`, `BACKFLOW`, or `FIRE_PUMP` — an `install_date` recording when the system was placed in service, and a `certification_cycle_anchor`, a valid calendar date that must fall in year 2000 — an anchor in any other year is rejected with `ERR_INVALID_REQUEST` — whose month and day are recorded as the certification-cycle anchor; the fee formulas of §3.3 do not consult it. A system's `impairment_status` is computed, starting at `NORMAL`, and its `status` starts `IN_SERVICE`.

Devices are the inspectable units of a system. Registering a device takes a `device_type` — one of `SMOKE_DETECTOR`, `PULL_STATION`, `NOTIFICATION_APPLIANCE`, `SPRINKLER_HEAD`, `GAUGE_VALVE`, `FIRE_PUMP_CONTROLLER`, `BACKFLOW_ASSEMBLY`, or `SUPERVISORY_SWITCH` — and a `serial_no` unique within the parent system (conflicts surface as `ERR_DUPLICATE_CONSTRAINT` with alias `ERR_DUPLICATE_DEVICE_SERIAL`). The device's `frequency_code` is derived from a fixed code table at creation: `FIRE_PUMP_CONTROLLER` devices are `MONTHLY`; `GAUGE_VALVE` and `SUPERVISORY_SWITCH` devices are `QUARTERLY`; `SMOKE_DETECTOR`, `PULL_STATION`, `NOTIFICATION_APPLIANCE`, `SPRINKLER_HEAD`, and `BACKFLOW_ASSEMBLY` devices are `ANNUAL`. The corresponding inspection intervals are one calendar month for `MONTHLY`, three calendar months for `QUARTERLY`, and twelve calendar months for `ANNUAL`.

Each device carries a computed `next_due_date`. The base for the computation is the completion date of the latest completed inspection event covering the device; if no such event exists, the base is the parent system's `install_date`. The next due date is the base plus the device's interval in calendar months, with month-end clamping. Device creation therefore immediately seeds `next_due_date` from the install date, and each event completion re-derives it from the completion date. Devices may be listed under their system with an optional `status` filter, or through the cross-entity device listing filtered by `system_id`, `replaced_by_device_id`, or `status`.

Field replacement is a first-class workflow. Marking a device replaced requires the device to be `IN_SERVICE`, the `replaced_by_device_id` pointer to reference a different `IN_SERVICE` device in the same system (violations raise `ERR_DEVICE_REPLACEMENT_MISMATCH`), and the device to carry no `OPEN` deficiency (otherwise `ERR_DEVICE_HAS_OPEN_DEFICIENCY`). The old device becomes `REPLACED`, and the replacement inherits urgency: its `next_due_date` becomes the earlier of its own current `next_due_date` and the replaced device's current `next_due_date`. Removing a device outright — again requiring `IN_SERVICE` and no `OPEN` deficiency — moves it to `REMOVED` and refreshes the current-year plan's requirement count. `REPLACED` and `REMOVED` devices are excluded from due-date sweeps.

Archiving a property is allowed only when the property is `ACTIVE`, every one of its systems has been `DECOMMISSIONED` (else `ERR_SYSTEMS_STILL_IN_SERVICE`), and no false-alarm case remains `OPEN` or `ASSESSED` for the property (else `ERR_UNRESOLVED_FALSE_ALARMS`). Archiving cascades any plan still in `DRAFT` or `SCHEDULED` to `LAPSED` — cancelling those plans' still-`SCHEDULED` child events, as in the lapse transition — and advances the property's `version`.

Decommissioning a system requires it to be `IN_SERVICE`, to have no impairment in `OPEN` or `NOTIFIED` (else `ERR_OPEN_IMPAIRMENT_EXISTS`), and to have no modification permit in `APPLIED`, `ISSUED`, or `WORK_COMMENCED` (else `ERR_OPEN_PERMIT_EXISTS`). The cascade removes every `IN_SERVICE` device (each becomes `REMOVED`), cancels every `SCHEDULED` inspection event referencing the system — each cancellation re-evaluating its parent plan's posture — forces the system's `impairment_status` to `OUT_OF_SERVICE`, and advances the system's `version`. A decommissioned system always reads `OUT_OF_SERVICE` regardless of impairment rows, and decommissioning halts scheduling and cancels open events. A `DECOMMISSIONED` system likewise rejects device registration, impairment opening, backflow and fire-pump test recording, and permit application, each failing with `ERR_INVALID_STATE`.

### 3.3. The Annual Inspection Plan and Its Fees

Planning is per property per calendar year. Creating a plan takes the `plan_year` and the OCC guard `expected_property_version`; the plan year is unique per property, so a second plan for the same property and year fails with `ERR_DUPLICATE_CONSTRAINT` (alias `ERR_DUPLICATE_PLAN_YEAR`). Creation itself increments the parent property's `version` by one, which is precisely the mutation a concurrent planner's stale `expected_property_version` protects against.

The plan's workload is computed from the property's device inventory at computation time. Each `IN_SERVICE` device on an `IN_SERVICE` system contributes events per year according to its frequency: twelve for `MONTHLY`, four for `QUARTERLY`, one for `ANNUAL`. Devices no longer in service contribute zero. The sum is `total_events_required`; `events_completed` counts child events in `COMPLETED` and starts at 0. The plan's own lifecycle is surfaced through its computed `plan_posture` field, which reads one of `DRAFT`, `SCHEDULED`, `IN_PROGRESS`, `FULFILLED`, or `LAPSED`. This requirement count is refreshed at plan creation, on device add, remove, or replacement, and when an event cancellation removes coverage. Only a plan not yet `FULFILLED` or `LAPSED` is refreshed; a terminal plan keeps its recorded counts.

Fees are prorated from annual base rates by system category: 120000 cents per year for `FIRE_ALARM`, 180000 for `SPRINKLER`, 9000 for `BACKFLOW`, and 240000 for `FIRE_PUMP`. The covered set is the property's `IN_SERVICE` systems at computation time. The service start is the later of the plan creation date and the latest `install_date` among covered systems; the certification year ends on December 31 of `plan_year`.

At creation, while the plan is `DRAFT`, the server computes `provisional_fee_cents` by calendar-day proration: for each covered system, the base annual fee is multiplied by the number of calendar days from the service start through December 31 inclusive (zero when the service start falls after that December 31) and divided by 365, with the per-system line rounded half-up to whole cents, and the lines summed.

When a `ContractorAdmin` publishes the plan — a transition requiring the plan to be `DRAFT`, `total_events_required` greater than zero (else `ERR_EMPTY_PLAN`), and the contractor in `GOOD_STANDING` (else `ERR_CONTRACTOR_POSTURE_BLOCKED`) — the plan becomes `SCHEDULED` and the server computes `final_fee_cents` by remaining-full-month proration: the number of whole calendar months strictly after the service start's month through December of the plan year (when the service start falls within the plan year, that is the months following its month through month twelve; when the service start predates the plan year, all twelve months count; when the service start falls after the plan year, no months count and the final fee is zero), each covered system's fee being its annual base multiplied by that month count and divided by twelve, rounded half-up per system line and then summed. The provisional figure is retained for audit.

Plan posture then evolves automatically. When the first child event moves to `IN_PROGRESS` or `COMPLETED`, a `SCHEDULED` plan becomes `IN_PROGRESS`. When `events_completed` reaches `total_events_required` and every child event is terminal with none in `NO_ACCESS`, the plan becomes `FULFILLED`, and the contractor's score is recomputed. When the logical date passes December 31 of the plan year without fulfillment, the plan becomes `LAPSED`: its still-`SCHEDULED` children are cancelled, and every `LAPSED` plan — whatever posture it lapsed from — feeds the 75-point lapsed-plan deduction of §2.9. Posture evaluation follows a deterministic order — the lapse check first when out of year, then fulfillment, then in-progress. A plan can never reach `FULFILLED` while any event is `NO_ACCESS` unless a replacement event is created to restore coverage.

### 3.4. Running Inspections: Scheduling, Field Execution, and Outcomes

Within a plan, a `ContractorAdmin` schedules inspection events — each event carrying its owning plan as `plan_id` — by naming the `system_id` under inspection — which must belong to the plan's property, else `ERR_CROSS_REFERENCE_MISMATCH` — the `lead_technician_id`, and the window `scheduled_start` to `scheduled_end`, where the end must be strictly after the start (else `ERR_INVALID_DATE_RANGE`). Assignment is capacity-checked: if the named technician already leads three other events in `SCHEDULED` or `IN_PROGRESS` whose closed-closed scheduled intervals intersect the new event's interval, the request is rejected with `ERR_TECHNICIAN_CAPACITY`. Scheduling is likewise rejected with `ERR_INVALID_STATE` when the plan is `FULFILLED` or `LAPSED`, when the named system is not `IN_SERVICE`, or when the named technician is not `ACTIVE`. Events may be browsed under their plan or through a cross-entity listing filtered by `lead_technician_id`, `system_id`, or `status`.

Field execution belongs to the assigned technician. Starting an event requires it to be `SCHEDULED`, the acting technician's identity to equal the event's `lead_technician_id` (else `ERR_TECHNICIAN_NOT_ASSIGNED`), the lead to hold an `ACTIVE` license whose class matches the system's category mapping — `ALARM` for `FIRE_ALARM`, `SPRINKLER` for `SPRINKLER`, `BACKFLOW` for `BACKFLOW`, `PUMP` for `FIRE_PUMP` — with `expires_on` strictly after the event's scheduled date (else `ERR_LICENSE_NOT_VALID`), the contractor not to be `SUSPENDED`, and the system's `impairment_status` not to be `OUT_OF_SERVICE` (else `ERR_SYSTEM_OUT_OF_SERVICE`). A successful start moves the event to `IN_PROGRESS` and re-evaluates the parent plan's posture, which may carry the plan from `SCHEDULED` to `IN_PROGRESS`.

Completing an event — again the assigned lead only, and only from `IN_PROGRESS` — is the richest transition in the system. The server stamps `completed_at` with the current clock and sets `report_due_date` to the completion date plus seven calendar days. Every covered device's `next_due_date` is recomputed from the completion date. The parent plan's `events_completed` increments and its posture is re-evaluated, possibly auto-fulfilling. A `DRAFT` marshal report is auto-created one-to-one for the event. Every `OPEN` deficiency recorded on the event receives its `correction_deadline` measured from the completion date. The contractor's score is recomputed, and an event completed on or before the latest covered device due date counts as on-time for the audited score's bonus — the covered devices being the event system's `IN_SERVICE` devices at completion, and an event covering none never counting as on-time. Both start and completion advance the event's `version`.

Two early terminations exist. A `ContractorAdmin` may cancel a `SCHEDULED` event, which re-evaluates plan posture and recomputes the plan's requirement count only if the cancellation removes plan coverage. The assigned technician may instead mark no-access, but only once the current clock has reached `scheduled_start` (attempting earlier yields `ERR_EVENT_NOT_YET_DUE`); the event becomes `NO_ACCESS`, every covered device keeps its old `next_due_date` — a missed inspection does not roll the due date forward — plan posture is re-evaluated with `NO_ACCESS` counting as terminal-but-unfulfilled, and the contractor absorbs the 20-point no-access deduction.

### 3.5. Deficiency Management and Correction Deadlines

During or after an inspection, the technician records each finding against the event with a `device_id` — which must belong to the event's system, else `ERR_CROSS_REFERENCE_MISMATCH` — and a `classification` of `CRITICAL` or `NONCRITICAL`. Recording requires the event to be `IN_PROGRESS` or `COMPLETED` — anything else yields `ERR_INVALID_STATE` — and any `Technician` may record a finding, not only the event's lead. New deficiencies open in `OPEN`, with `extension_used` false, `late_fee_cents` zero, and `corrected_at` null; recording one refreshes the contractor's posture derivation. The `correction_deadline` is computed from the parent event's completion date — assigned immediately at recording when the event is already `COMPLETED`, otherwise deferred until event completion per §3.4 — and equals the completion date plus one day for `CRITICAL` findings, or the completion date plus thirty days for `NONCRITICAL` findings. Deficiencies may be listed under their event or through the cross-entity listing filtered by `event_id`, `device_id`, or `status`.

Late fees accrue deterministically. The number of days late is the days between the relevant date — `corrected_at` when a correction is being attested, the current logical date during the daily sweep — and the `correction_deadline`, never below zero, and capped at thirty days. The fee is those days multiplied by 20000 cents per day for `CRITICAL` or 5000 cents per day for `NONCRITICAL`, an integer-cents product with no rounding. The sweep keeps `late_fee_cents` current while a deficiency stands open past deadline, and each open overdue deficiency is simultaneously feeding the contractor's score deduction (40 or 10 points by classification).

Correction is a two-signature affair. A `ContractorAdmin` attests correction on an `OPEN` deficiency whose parent event is `COMPLETED` (else `ERR_EVENT_NOT_COMPLETED`); the server stamps `corrected_at`, computes the final late fee against the deadline, recomputes the contractor's score — an on-time correction lets the overdue deduction drop off, while a late correction keeps it — and moves the deficiency to `CORRECTED`. Verification is then a `FireMarshal` action with a hard segregation-of-duties rule: the verifying marshal's `X-User-ID` must differ from the `X-User-ID` that performed the attestation, else `ERR_SEGREGATION_OF_DUTIES`. Verification lands in `VERIFIED`, the terminal-accepted state.

A marshal who disputes the correction rejects it, returning the deficiency from `CORRECTED` to `OPEN`: `corrected_at` is cleared to null and late-fee accrual resumes against the original `correction_deadline` — no reset is granted. Alternatively, a marshal may waive a deficiency directly from `OPEN`, but only when `classification` is `NONCRITICAL`; waiving a critical finding is refused with `ERR_CRITICAL_NOT_WAIVABLE`. Waiver zeroes `late_fee_cents`, lands in `WAIVED`, and trades the overdue deduction for the 5-point waiver penalty in the score recompute.

Deadline relief is narrow. A marshal may extend a deficiency's deadline by thirty days exactly once, and only for an `OPEN`, `NONCRITICAL` deficiency whose `extension_used` is still false; any other target — a critical finding, a non-open deficiency, or a second extension — is rejected with `ERR_DEFICIENCY_NOT_EXTENSIBLE`. A granted extension adds thirty days to `correction_deadline` and flips `extension_used` to true. When the deadline has not yet been assigned (the event is not yet `COMPLETED`), the extension still consumes the single allowance — `extension_used` flips to true — without moving any date.

### 3.6. Impairments and Authority Notification

When a system cannot perform its protective function, a `ContractorAdmin` opens an impairment with an `impairment_kind` of `PLANNED` or `UNPLANNED` and a window from `planned_start` to `planned_end`, the end strictly after the start. Both kinds carry the client-supplied window — for an `UNPLANNED` impairment the supplied `planned_start` conventionally denotes the discovery time — and `discovered_at` is stamped server-side at creation for both kinds. The notification deadline depends on kind: for `PLANNED` it is eight hours before `planned_start`; for `UNPLANNED` it is two hours after `discovered_at`.

Planned impairments on the same system are serialized. A new `PLANNED` impairment is rejected with `ERR_IMPAIRMENT_OVERLAP` when its half-open window — start inclusive, end exclusive — overlaps that of any other non-`CLOSED` impairment on the system, or when it starts inside the four-hour re-certification buffer following another impairment that ends before it: the new start must be at least four hours after the other's `planned_end`, a start exactly equal to the other's end is inside the buffer and rejected, and a start exactly four hours after the other's end is allowed.

The system's `impairment_status` is derived continuously from its impairment rows: while any impairment in `OPEN` or `NOTIFIED` has a `planned_start` lying strictly more than ten hours in the past (exactly ten hours does not suffice), the system reads `OUT_OF_SERVICE`; otherwise, with at least one impairment in `OPEN` or `NOTIFIED`, it reads `IMPAIRED`; with none, `NORMAL`. This derivation runs on impairment creation, restoration, and closure — and a `DECOMMISSIONED` system always reads `OUT_OF_SERVICE`.

Notifying the authority moves an `OPEN` impairment to `NOTIFIED`: the server stamps `authority_notified_at` with the current clock, computes `notification_late` as true exactly when the notification time is strictly after the `notification_deadline` (stamping at the deadline itself is on time), and, when late, recomputes the contractor's score with the 60-point late-notification deduction. Restoration — permitted from either `OPEN` or `NOTIFIED` — stamps `restored_at`, moves the impairment to `RESTORED`, and re-derives the system's impairment status, returning it toward `NORMAL` when no other open impairments remain. Final closure from `RESTORED` to `CLOSED` belongs to the `FireMarshal`.

### 3.7. Marshal Reports and the Portal Submission Loop

Every completed inspection event owns a one-to-one marshal report, auto-created in `DRAFT` at completion. Submission is a `ContractorAdmin` action requiring the report to be `DRAFT`, the parent event to be `COMPLETED` (else `ERR_EVENT_NOT_COMPLETED`), and the contractor not `SUSPENDED`. The server stamps `submitted_at`, computes `is_late` as true exactly when the submitted date is strictly after the event's `report_due_date` (submission on the due date itself is on time), and, when late, applies the 25-point late-report deduction. The report becomes `SUBMITTED`.

Adjudication sits with the `FireMarshal`. Acceptance requires a `SUBMITTED` report and a clean deficiency posture on the parent event: every deficiency must be in `VERIFIED` or `WAIVED`, or still within its `correction_deadline` window — an overdue, unresolved deficiency blocks acceptance with `ERR_UNRESOLVED_OVERDUE_DEFICIENCIES`. Acceptance stamps the `portal_submission_id`, a server-minted receipt token that is not a UUID: it is the parent property's jurisdiction code followed by a hyphen and a zero-padded eight-digit counter, sequential per jurisdiction and starting at 1. Rejection, also from `SUBMITTED`, lands in `REJECTED` and reopens the revision loop.

The revision loop is expressed across two rows. A `ContractorAdmin` creates a revision by posting a new report against the same event with `revision_of_id` pointing at the rejected report; the pointer must reference a report that exists, is `REJECTED`, and belongs to the same event, else `ERR_REPORT_REVISION_INVALID`. The rejected report remains `REJECTED` for audit, and the new report starts its own lifecycle in `DRAFT`. Reports may be listed under their event — the active one-to-one report plus any revisions — or through the cross-entity listing filtered by `event_id`, `revision_of_id`, or `status`.

### 3.8. Specialty Testing and False Alarm Adjudication

**Backflow testing.** A backflow test is recorded against a `BACKFLOW`-category system — any other category yields the `ERR_SYSTEM_CATEGORY_MISMATCH` alias of `ERR_CROSS_REFERENCE_MISMATCH` — naming the `device_id` under test — which must reference a `BACKFLOW_ASSEMBLY` device belonging to that system, else `ERR_CROSS_REFERENCE_MISMATCH` — the `tester_technician_id`, the `tested_at` timestamp, and a `result` of `PASS` or `FAIL`. The tester must hold an `ACTIVE` `BACKFLOW` license valid on the test date, enforced as `ERR_LICENSE_NOT_VALID`. A `FAIL` result auto-transitions the record to `FAILED_OPEN` at creation: the device's due date is unchanged, a re-test means a new test row, and the contractor takes the 30-point failed-specialty-test deduction. A passing test sits in `RECORDED` with `unpaid_balance_cents` at zero.

Billing follows the pass. Invoicing a `RECORDED` test — allowed only when `result` is `PASS`, since a failed result is already routed to `FAILED_OPEN` and invoicing anything else is `ERR_INVALID_STATE` — sets `unpaid_balance_cents` to the standard test fee of 40000 cents and moves the record to `INVOICED`. Payment becomes due thirty days after the invoice transition. While the balance stands unpaid past that due date, the penalty compounds monthly at five percent: for each whole calendar month elapsed from the due date to the payment date — a partial month does not compound — the balance is multiplied by 1.05 and rounded half-up to whole cents after each monthly step, starting from the 40000-cent base. Recording payment against an `INVOICED` test first computes this compounded penalty into `unpaid_balance_cents`, then zeroes the balance and lands in `PAID`.

**Fire-pump testing.** A fire-pump test is recorded against a `FIRE_PUMP`-category system with a `test_kind` of `CHURN` (performed monthly) or `ANNUAL_FLOW` (performed yearly), a `tester_technician_id` holding an `ACTIVE` `PUMP` license whose expiry is strictly after the test date, the `tested_at` timestamp, and a `result`. The `coordinated_event_id` field is nullable in general but mandatory for `ANNUAL_FLOW`: it must reference a completed inspection event covering the same system, and attestation enforces this — an annual flow test without a qualifying coordinated event fails with `ERR_PUMP_COORDINATION_REQUIRED`. A `FAIL` result again auto-routes to `FAILED_OPEN` with the 30-point deduction. A `ContractorAdmin` attests a `RECORDED` test whose `result` is `PASS`, landing it in `ATTESTED`; anything else is `ERR_INVALID_STATE`. Both specialty-test families offer per-system listings and cross-entity listings — backflow tests filterable by `system_id`, `device_id`, or `tester_technician_id`, pump tests by `system_id`, `tester_technician_id`, or `coordinated_event_id`.

**False alarms.** The `FireMarshal` records each false-alarm activation against a property with `alarm_occurred_at` and a `cause_code` of `NEGLIGENCE`, `EQUIPMENT_FAULT`, `UNKNOWN`, `MALICIOUS`, or `WEATHER`. Only `NEGLIGENCE`, `EQUIPMENT_FAULT`, and `UNKNOWN` are chargeable; the server computes `chargeable` accordingly; a non-chargeable case carries no `sequence_number` (null), and assessing a non-chargeable case sets a zero fee. For a chargeable case, `sequence_number` is computed as one plus the count of the property's other chargeable, non-`WAIVED` cases whose alarm dates fall within the trailing 365-day window — on or after 364 days before the current alarm's date and strictly before it — making the sequence number the one-indexed position within the rolling window ending on the alarm date inclusive.

Assessment moves the case from `OPEN` to `ASSESSED` and computes `fee_cents` from the sequence number and the property's occupancy class. In the standard schedule — every class except `RESIDENTIAL` — the first and second chargeable cases in the window cost nothing, the third and fourth cost 15000 cents each tier-wide, the fifth and sixth 30000, and the seventh and beyond 50000. For a `RESIDENTIAL` property every tier is halved with round-half-up applied to the halved tier: free, 7500, 15000, and 25000 respectively. In both variants a habitual surcharge of 25000 cents is added whenever the sequence number is at least seven. The fee is the tier plus the surcharge, in integer cents. When the cause is `NEGLIGENCE`, assessment also applies the 15-point negligence deduction to the contractor. A marshal may waive a case from either `OPEN` or `ASSESSED`, which zeroes `fee_cents`, sets `waived` true, and lands in `WAIVED`; a waived case no longer counts in future sequence windows. Payment by the `ContractorAdmin` moves an `ASSESSED` case to `PAID`. Cases are listed per property with an optional `status` filter.

### 3.9. System Modification Permits

Any modification to a protected system requires a permit. Applying takes the declared `project_valuation_cents` — a non-negative integer, a negative valuation being rejected with `ERR_INVALID_REQUEST` — and the OCC guard `expected_system_version`; the application itself increments the parent system's `version`, so a stale expected version is rejected with `ERR_STALE_VERSION` and the applicant must re-read the system. The application computes `permit_fee_cents` from the valuation on a marginal tier schedule: the first 200000 cents of valuation are charged at three percent, the next 300000 cents at two and a half percent, and any remainder at one and a half percent; the result is floored at a minimum fee of 7500 cents, and a single round-half-up to whole cents is applied at the very end — no per-tier rounding. The permit starts in `APPLIED`, and permits may be listed per system.

Issuance is a `FireMarshal` decision requiring the permit to be `APPLIED`, the contractor in `GOOD_STANDING`, and the system's `impairment_status` exactly `NORMAL` — issuance against an impaired or out-of-service system fails with `ERR_SYSTEM_IMPAIRED`. Once `ISSUED`, the permit is valid for ninety days: a `ContractorAdmin` attesting work commencement must do so on or before the issue date plus ninety days, else `ERR_PERMIT_EXPIRED`. Commencement stamps `work_commenced_at` and has a structural side effect: because the system is being opened up, an `UNPLANNED` impairment is auto-created on the system with `discovered_at` set to the commencement instant and a planned window running from the commencement instant to eight hours after it, which itself requires authority notification within two hours and immediately re-derives the system's impairment status. Permits still `ISSUED` with no commencement when the logical date passes the issue date plus ninety days are swept to `EXPIRED` by the daily sweep.

Closing a permit is a marshal action from `WORK_COMMENCED` with two preconditions: the auto-created impairment for the permit must be `CLOSED` (else `ERR_OPEN_IMPAIRMENT_EXISTS`), and a post-modification inspection event on the system must be `COMPLETED` with a `completed_at` strictly after `work_commenced_at` (else `ERR_POST_MOD_INSPECTION_REQUIRED`). Closure re-seeds device frequencies: any device whose device-type mapping changed gets its `next_due_date` recomputed from the close date — and since the device-type→frequency mapping is a fixed code table, no device's mapping can ever change, so in practice closure alters no due date.

Finally, a marshal who finds evidence that work began before issuance cites unpermitted work. The citation endpoint takes a request field `unpermitted_work_detected`, which must be true — any other value is `ERR_INVALID_REQUEST` — and applies from either `APPLIED` or `ISSUED`. The penalty is severe: `permit_fee_cents` is doubled, the contractor's score absorbs the 100-point unpermitted-work deduction, and the permit lands in its terminal `FINED` state.

---

## 4. Endpoint Definitions

All endpoints are mounted under `/fire-compliance`. Creating a new resource returns HTTP 201 with the created resource; state transitions, modifications, and retrievals return HTTP 200 with the affected or requested resource. All requests require the authentication headers of §2.1, and all list endpoints follow the pagination contract of §2.3.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/fire-compliance/_clock/set_current_utc` | Set the server's logical clock (startup default `2026-08-01T00:00:00Z`) and run the daily sweep | FireMarshal |
| POST | `/fire-compliance/contractors` | Register a contractor | FireMarshal |
| GET | `/fire-compliance/contractors/{id}` | Fetch one contractor | FireMarshal, ContractorAdmin, Technician |
| GET | `/fire-compliance/contractors` | List contractors (`posture?` filter, paginated) | FireMarshal, ContractorAdmin |
| POST | `/fire-compliance/contractors/{id}/deactivate` | Deactivate contractor (cascades technicians, impairments, draft reports) | FireMarshal |
| POST | `/fire-compliance/contractors/{id}/audit-score` | Compute the audited compliance-score variant (not persisted) | FireMarshal |
| POST | `/fire-compliance/contractors/{id}/technicians` | Add a technician to a contractor | ContractorAdmin |
| GET | `/fire-compliance/contractors/{id}/technicians` | List a contractor's technicians | FireMarshal, ContractorAdmin |
| GET | `/fire-compliance/technicians/{id}` | Fetch one technician | FireMarshal, ContractorAdmin, Technician |
| POST | `/fire-compliance/technicians/{id}/deactivate` | Deactivate a technician (sweeps lapsed licenses) | ContractorAdmin |
| POST | `/fire-compliance/technicians/{id}/license-records` | Record a technician license | ContractorAdmin |
| GET | `/fire-compliance/technicians/{id}/license-records` | List a technician's license records | FireMarshal, ContractorAdmin, Technician |
| GET | `/fire-compliance/license-records/{id}` | Fetch one license record | FireMarshal, ContractorAdmin |
| POST | `/fire-compliance/license-records/{id}/revoke` | Revoke a license | FireMarshal |
| POST | `/fire-compliance/properties` | Register a property under a contractor of record | ContractorAdmin |
| GET | `/fire-compliance/properties/{id}` | Fetch one property | FireMarshal, ContractorAdmin, Technician |
| GET | `/fire-compliance/properties` | List properties (`contractor_id?`, `occupancy_class?` filters, paginated) | FireMarshal, ContractorAdmin |
| POST | `/fire-compliance/properties/{id}/archive` | Archive a property (lapses draft/scheduled plans) | ContractorAdmin |
| POST | `/fire-compliance/properties/{id}/systems` | Register a protected system on a property | ContractorAdmin |
| GET | `/fire-compliance/properties/{id}/systems` | List systems of a property | FireMarshal, ContractorAdmin, Technician |
| GET | `/fire-compliance/systems/{id}` | Fetch one system | FireMarshal, ContractorAdmin, Technician |
| POST | `/fire-compliance/systems/{id}/decommission` | Decommission a system (removes devices, cancels events) | ContractorAdmin |
| POST | `/fire-compliance/systems/{id}/devices` | Register a device in a system (derives frequency and due date) | ContractorAdmin |
| GET | `/fire-compliance/systems/{id}/devices` | List devices of a system (`status?` filter) | FireMarshal, ContractorAdmin, Technician |
| GET | `/fire-compliance/devices/{id}` | Fetch one device | FireMarshal, ContractorAdmin, Technician |
| POST | `/fire-compliance/devices/{id}/replace` | Mark a device replaced by another in the same system (due-date inheritance) | ContractorAdmin |
| POST | `/fire-compliance/devices/{id}/remove` | Remove a device from service | ContractorAdmin |
| POST | `/fire-compliance/properties/{id}/inspection-plans` | Create an annual inspection plan (OCC-guarded on the property's version) | ContractorAdmin |
| GET | `/fire-compliance/properties/{id}/inspection-plans` | List plans of a property | FireMarshal, ContractorAdmin |
| GET | `/fire-compliance/inspection-plans/{id}` | Fetch one plan | FireMarshal, ContractorAdmin |
| POST | `/fire-compliance/inspection-plans/{id}/publish` | Publish a plan (computes the final prorated fee) | ContractorAdmin |
| POST | `/fire-compliance/inspection-plans/{id}/events` | Schedule an inspection event under a plan (capacity-checked) | ContractorAdmin |
| GET | `/fire-compliance/inspection-plans/{id}/events` | List events of a plan (`status?` filter) | FireMarshal, ContractorAdmin, Technician |
| GET | `/fire-compliance/inspection-events/{id}` | Fetch one event | FireMarshal, ContractorAdmin, Technician |
| GET | `/fire-compliance/inspection-events` | Filtered list of events (`lead_technician_id?`, `system_id?`, `status?`) | FireMarshal, ContractorAdmin, Technician |
| POST | `/fire-compliance/inspection-events/{id}/start` | Start an event (assigned lead technician only) | Technician |
| POST | `/fire-compliance/inspection-events/{id}/complete` | Complete an event (stamps report due date, auto-creates draft report) | Technician |
| POST | `/fire-compliance/inspection-events/{id}/cancel` | Cancel a scheduled event | ContractorAdmin |
| POST | `/fire-compliance/inspection-events/{id}/mark-no-access` | Mark no-access (assigned lead, only at/after scheduled start) | Technician |
| POST | `/fire-compliance/inspection-events/{id}/deficiencies` | Record a deficiency found during an event | Technician |
| GET | `/fire-compliance/inspection-events/{id}/deficiencies` | List deficiencies of an event | FireMarshal, ContractorAdmin, Technician |
| GET | `/fire-compliance/deficiencies/{id}` | Fetch one deficiency | FireMarshal, ContractorAdmin, Technician |
| POST | `/fire-compliance/deficiencies/{id}/attest-correction` | Attest correction (computes final late fee) | ContractorAdmin |
| POST | `/fire-compliance/deficiencies/{id}/verify` | Verify a correction (segregation of duties enforced) | FireMarshal |
| POST | `/fire-compliance/deficiencies/{id}/reject-correction` | Reject a correction (reopens with the original deadline) | FireMarshal |
| POST | `/fire-compliance/deficiencies/{id}/waive` | Waive a noncritical deficiency | FireMarshal |
| POST | `/fire-compliance/deficiencies/{id}/extend-deadline` | Grant the one-time thirty-day extension (noncritical only) | FireMarshal |
| POST | `/fire-compliance/systems/{id}/impairments` | Open an impairment (planned or unplanned; overlap and buffer checked) | ContractorAdmin |
| GET | `/fire-compliance/systems/{id}/impairments` | List impairments of a system (`status?` filter) | FireMarshal, ContractorAdmin, Technician |
| GET | `/fire-compliance/impairments/{id}` | Fetch one impairment | FireMarshal, ContractorAdmin, Technician |
| POST | `/fire-compliance/impairments/{id}/notify-authority` | Record authority notification (computes lateness) | ContractorAdmin |
| POST | `/fire-compliance/impairments/{id}/restore` | Mark service restored | ContractorAdmin |
| POST | `/fire-compliance/impairments/{id}/close` | Close an impairment | FireMarshal |
| GET | `/fire-compliance/inspection-events/{id}/marshal-reports` | List marshal reports of an event (active plus revisions) | FireMarshal, ContractorAdmin |
| POST | `/fire-compliance/inspection-events/{id}/marshal-reports` | Create a revision report for a rejected report on the event | ContractorAdmin |
| GET | `/fire-compliance/marshal-reports/{id}` | Fetch one report | FireMarshal, ContractorAdmin |
| POST | `/fire-compliance/marshal-reports/{id}/submit` | Submit a report to the portal (computes lateness) | ContractorAdmin |
| POST | `/fire-compliance/marshal-reports/{id}/accept` | Accept a report (stamps the portal receipt token) | FireMarshal |
| POST | `/fire-compliance/marshal-reports/{id}/reject` | Reject a report (reopens the revision loop) | FireMarshal |
| POST | `/fire-compliance/systems/{id}/backflow-tests` | Record a backflow test (license- and category-checked) | ContractorAdmin |
| GET | `/fire-compliance/systems/{id}/backflow-tests` | List backflow tests of a system | FireMarshal, ContractorAdmin |
| GET | `/fire-compliance/backflow-tests/{id}` | Fetch one backflow test | FireMarshal, ContractorAdmin |
| POST | `/fire-compliance/backflow-tests/{id}/invoice` | Invoice a passing backflow test | ContractorAdmin |
| POST | `/fire-compliance/backflow-tests/{id}/record-payment` | Record payment (computes the compounded late penalty) | ContractorAdmin |
| POST | `/fire-compliance/systems/{id}/fire-pump-tests` | Record a fire-pump test (churn or annual flow) | ContractorAdmin |
| GET | `/fire-compliance/systems/{id}/fire-pump-tests` | List fire-pump tests of a system | FireMarshal, ContractorAdmin |
| GET | `/fire-compliance/fire-pump-tests/{id}` | Fetch one fire-pump test | FireMarshal, ContractorAdmin |
| POST | `/fire-compliance/fire-pump-tests/{id}/attest` | Attest a passing pump test (coordination enforced for annual flow) | ContractorAdmin |
| POST | `/fire-compliance/properties/{id}/false-alarm-cases` | Record a false alarm | FireMarshal |
| GET | `/fire-compliance/properties/{id}/false-alarm-cases` | List false-alarm cases of a property (`status?` filter) | FireMarshal, ContractorAdmin |
| GET | `/fire-compliance/false-alarm-cases/{id}` | Fetch one false-alarm case | FireMarshal, ContractorAdmin |
| POST | `/fire-compliance/false-alarm-cases/{id}/assess` | Assess the false-alarm fee | FireMarshal |
| POST | `/fire-compliance/false-alarm-cases/{id}/waive` | Waive the false-alarm fee | FireMarshal |
| POST | `/fire-compliance/false-alarm-cases/{id}/record-payment` | Record fee payment | ContractorAdmin |
| POST | `/fire-compliance/systems/{id}/modification-permits` | Apply for a modification permit (OCC-guarded on the system's version) | ContractorAdmin |
| GET | `/fire-compliance/systems/{id}/modification-permits` | List permits of a system | FireMarshal, ContractorAdmin |
| GET | `/fire-compliance/modification-permits/{id}` | Fetch one permit | FireMarshal, ContractorAdmin |
| POST | `/fire-compliance/modification-permits/{id}/issue` | Issue a permit | FireMarshal |
| POST | `/fire-compliance/modification-permits/{id}/commence-work` | Attest work commencement (auto-creates an unplanned impairment) | ContractorAdmin |
| POST | `/fire-compliance/modification-permits/{id}/close` | Close a permit after post-modification inspection | FireMarshal |
| POST | `/fire-compliance/modification-permits/{id}/cite-unpermitted-work` | Cite unpermitted work (doubles the fee) | FireMarshal |
| GET | `/fire-compliance/devices` | Cross-entity device list (`system_id?`, `replaced_by_device_id?`, `status?`) | FireMarshal, ContractorAdmin, Technician |
| GET | `/fire-compliance/deficiencies` | Cross-entity deficiency list (`event_id?`, `device_id?`, `status?`) | FireMarshal, ContractorAdmin, Technician |
| GET | `/fire-compliance/marshal-reports` | Cross-entity report list (`event_id?`, `revision_of_id?`, `status?`) | FireMarshal, ContractorAdmin |
| GET | `/fire-compliance/backflow-tests` | Cross-entity backflow-test list (`system_id?`, `device_id?`, `tester_technician_id?`) | FireMarshal, ContractorAdmin |
| GET | `/fire-compliance/fire-pump-tests` | Cross-entity pump-test list (`system_id?`, `tester_technician_id?`, `coordinated_event_id?`) | FireMarshal, ContractorAdmin |

---

## 5. Error Code Catalogue

The catalogue below enumerates every error identifier and its HTTP status. The conditions that trigger each error are specified in §2 and §3 alongside the workflows they guard.

| Error ID | HTTP Status Code |
|---|---|
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_REFERENCE_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_ENUM` | 422 |
| `ERR_INVALID_DATE_RANGE` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_CONTRACTOR_POSTURE_BLOCKED` | 409 |
| `ERR_SYSTEM_OUT_OF_SERVICE` | 409 |
| `ERR_SYSTEM_IMPAIRED` | 422 |
| `ERR_LICENSE_NOT_VALID` | 422 |
| `ERR_TECHNICIAN_NOT_ASSIGNED` | 403 |
| `ERR_TECHNICIAN_CAPACITY` | 409 |
| `ERR_IMPAIRMENT_OVERLAP` | 409 |
| `ERR_DUPLICATE_CONSTRAINT` | 409 |
| `ERR_CROSS_REFERENCE_MISMATCH` | 422 |
| `ERR_OPEN_ITEMS_BLOCK` | 409 |
| `ERR_CRITICAL_NOT_WAIVABLE` | 422 |
| `ERR_EMPTY_PLAN` | 422 |
| `ERR_EVENT_NOT_COMPLETED` | 409 |
| `ERR_EVENT_NOT_YET_DUE` | 422 |
| `ERR_UNRESOLVED_OVERDUE_DEFICIENCIES` | 409 |
| `ERR_REPORT_REVISION_INVALID` | 422 |
| `ERR_PUMP_COORDINATION_REQUIRED` | 422 |
| `ERR_PERMIT_EXPIRED` | 409 |
| `ERR_POST_MOD_INSPECTION_REQUIRED` | 409 |
| `ERR_DEFICIENCY_NOT_EXTENSIBLE` | 422 |
