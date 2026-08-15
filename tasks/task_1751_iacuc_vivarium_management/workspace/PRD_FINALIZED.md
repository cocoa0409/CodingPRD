# IACUC & Vivarium Management API — Product Requirements Document

## 1. Introduction

Universities that run animal research programs operate under continuous regulatory scrutiny: every protocol must pass Institutional Animal Care and Use Committee (IACUC) review, every animal must be accounted for daily, and every dollar of per-diem cost must be traceable back to a sponsor award. The IACUC & Vivarium Management API is the operational backbone for such a program. It coordinates protocol submission with species and number justification, designated-member versus full-committee review, semiannual facility inspection and program review, animal census with per-diem billing to grants, breeding-colony management with cage-capacity enforcement, veterinary care with adverse-condition reporting, training and occupational-health enrollment for personnel, and the deviation-to-suspension disciplinary chain.

The design is deliberately audit-first. Lifecycle states are explicit and every transition is guarded; financial computation runs in two variants — a fast provisional pass over raw occupancy and a reconciled final pass over confirmed census — so a billing coordinator can preview charges before any grant is debited; and a logical, test-drivable clock governs every time-based rule in the system, from the 21-day weaning age to the three-year protocol expiry. This document is the complete product specification for that API.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the operational capacity in which they act. A request missing either header, or presenting a role the system does not recognize, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is recognized but not permitted for the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403). The system recognizes exactly eight roles: `IacucAdministrator`, `Investigator`, `AnimalCareStaff`, `AttendingVeterinarian`, `FacilityManager`, `BillingCoordinator`, `TrainingCoordinator`, and `OccHealthNurse`.

Identity binding differs by role. When `X-User-Role` is `Investigator`, `X-User-ID` is the `id` of the acting Investigator; ownership checks on any resource that references an Investigator compare the resource's foreign-key field — for example, a protocol's `investigator_id` — to `X-User-ID`, and a mismatch is rejected with `ERR_NOT_OWNER` (HTTP 403). When `X-User-Role` is `AnimalCareStaff` or `AttendingVeterinarian`, `X-User-ID` is the `id` of the acting Personnel record; ownership-style checks, such as the segregation-of-duties rule that the reporter of a deviation may not also close it, compare personnel foreign keys such as `reported_by_personnel_id` against `X-User-ID`. When `X-User-Role` is `IacucAdministrator`, `FacilityManager`, `BillingCoordinator`, `TrainingCoordinator`, or `OccHealthNurse`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but never compares it to any entity's `id`.

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

List endpoints paginate through two query parameters. `limit` caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` skips that many items from the front of the result set and defaults to 0. Unless otherwise specified, every list endpoint returns its resources sorted by `created_at` in ascending order. The `meta` object of a list response carries four pagination fields: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock and Time-Driven Transitions

The server runs on a logical clock, never on wall-clock time. At startup the logical clock reads exactly 2026-08-01T00:00:00Z, and the server must not fall back to wall-clock time under any circumstances. An administrator-only, test-driving capability sets the logical clock to a supplied instant provided in the request body as `to_iso8601`, and responds with the resulting time as `current_utc`. Setting the clock triggers every time-based transition defined in this document — protocol expiry, training-enrollment expiry, occupational-health clearance expiry, inspection lapse detection, and the automatic escalation of `UNDER_TREATMENT` adverse-event reports whose 72-hour resolution deadline has been breached (§3.8) — while procedure-room bookings are left unchanged by clock movement. Every deadline in this document, including the 21-day weaning age, the 72-hour resolution window, inspection `due_by`, and enrollment and protocol `expires_at`, is evaluated against this logical clock.

### 2.5. Common Resource Properties

Every resource in the system carries a standard set of system-managed fields:

- `id` (string): a unique, server-generated identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording the most recent modification of the resource.
- `version` (integer): a system-managed integer that increments on every mutation of the resource, including mutations produced by cascading side effects and recomputed fields.

### 2.6. Nested Resource Retrieval

Requests that address a resource nested beneath another — for example, the collection of animals belonging to a cage, or the grants belonging to an investigator — are validated left to right along the path. Each path identifier must resolve to an existing row before the next identifier is examined, and the request is rejected with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that fails to resolve. Foreign keys supplied in a request body are validated the same way: any referenced resource that does not exist produces `ERR_NOT_FOUND` before further business rules are evaluated.

### 2.7. Optimistic Concurrency Control

Two write operations in the system are guarded by optimistic concurrency control, and they are the only endpoints that accept a version field:

- Finalizing a billing run requires the request body to carry `expected_billing_run_version`, holding the run `version` the client last observed. If the run's current `version` has advanced since that observation — because another writer has already finalized or voided the run — the finalize is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from acting on a run whose contents it has not observed.
- Suspending a protocol requires the request body to carry `expected_protocol_version`, holding the protocol `version` the client last observed. If the protocol's current `version` has advanced since that observation, the suspension is rejected with `ERR_STALE_VERSION` (HTTP 412), and the client must re-read the protocol before retrying.

No other endpoint takes a version field. Omitting the expected-version field from either guarded request is a malformed request and fails payload validation.

### 2.8. Validation Pipeline and Priority Order

When several checks could reject the same request, the server evaluates them in a single fixed priority order and surfaces the earliest failure. From first to last:

1. Authentication — presence and well-formedness of `X-User-ID` and `X-User-Role` (`ERR_UNAUTHENTICATED`, 401).
2. Role permission for the endpoint (`ERR_FORBIDDEN`, 403).
3. Payload well-formedness — required fields present and well-typed, enum values within their declared sets, integers within range (`ERR_INVALID_REQUEST`, 400).
4. Existence — every path identifier and every body foreign key resolves to an existing row (`ERR_NOT_FOUND`, 404).
5. Ownership — on ownership-checked operations, `X-User-ID` matches the resource's owner foreign key (`ERR_NOT_OWNER`, 403).
6. State legality — the target resource is in a state from which the requested transition exists (`ERR_INVALID_STATE`, 409).
7. Optimistic concurrency — the expected-version field matches the current `version` on the two guarded writes (`ERR_STALE_VERSION`, 412).
8. Segregation of duties (`ERR_SEGREGATION_OF_DUTIES`, 403).
9. Personnel gates — training and occupational-health clearance (`ERR_TRAINING_INCOMPLETE`, 422).
10. The protocol animal ceiling (`ERR_ANIMAL_CAP_EXCEEDED`, 422).
11. The protocol-approved gate (`ERR_PROTOCOL_NOT_APPROVED`, 409).
12. The serious-deviation close restriction (`ERR_SERIOUS_DEVIATION_NOT_CLOSABLE`, 422).
13. Species and protocol consistency between animal and cage (`ERR_CAGE_MISMATCH`, 422).
14. Cage capacity (`ERR_CAGE_OVER_CAPACITY`, 422).
15. Vote-tally validity (`ERR_INVALID_VOTE_TALLY`, 422).
16. Booking not in the past (`ERR_BOOKING_IN_PAST`, 422).
17. Room conflict (`ERR_ROOM_CONFLICT`, 409).
18. Weaning age (`ERR_LITTER_TOO_YOUNG`, 422).
19. Adverse-event resolution deadline (`ERR_RESOLUTION_OVERDUE`, 422).
20. Inspection lapse (`ERR_INSPECTION_LAPSED`, 422).
21. Census discrepancy (`ERR_CENSUS_DISCREPANCY`, 422).
22. Grant solvency at posting (`ERR_GRANT_INSOLVENT`, 402).
23. Grant solvency at protocol submission (`ERR_GRANT_EXHAUSTED`, 402).
24. Uniqueness (`ERR_DUPLICATE`, 409).

The ordering is observable. Adding an animal to a protocol that is simultaneously at its justified ceiling and not yet approved surfaces `ERR_ANIMAL_CAP_EXCEEDED`, because the ceiling check precedes the approval gate. On a cage-to-cage transfer, a species or protocol disagreement surfaces as `ERR_CAGE_MISMATCH` even when the target cage is also full, because consistency is checked before capacity. On a room booking, an unclear personnel member produces `ERR_TRAINING_INCOMPLETE` before any past-dated or conflicting slot is examined. Uniqueness is always the final check: a duplicate `email`, `grant_number`, `cage_barcode`, `animal_tag`, or `protocol_number` surfaces only after every other applicable rule has passed.

### 2.9. Monetary Precision and Rounding Conventions

All money in the system is integer cents. Budgets (`budget_total_cents`, `budget_remaining_cents`), per-diem rates (`rate_cents`), and charge amounts (`amount_cents`) are integers; no fractional cents exist anywhere. Within a per-diem computation, each day's charge is rounded half-up to integer cents before the days are summed into the line amount. The one non-integer computed figure in the system is the breeding productivity `score`, which is reported rounded half-up to two decimal places. Datetimes compared for scheduling purposes — inspection deadlines and booking buffers — are compared to the second.

### 2.10. Segregation of Duties

Two duties are segregated by identity. First, an investigator may not record committee review decisions on their own protocol: when review decisions are recorded, the acting `X-User-ID` must not equal the protocol's owning `investigator_id`. Second, the person who reported a protocol deviation may not close it: closing a deviation requires that the acting `X-User-ID` differ from the deviation's `reported_by_personnel_id`. Either violation is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).

### 2.11. Hierarchical Consistency and Cascading Effects

State changes propagate across aggregate boundaries. Suspending a protocol freezes its occupied cages and escalates its open veterinary cases; imposing a suspension from a deviation suspends the protocol, which in turn cascades to cages and adverse-event reports; placing, moving, weaning, retiring, or euthanizing animals recomputes cage occupancy and can flip a cage among `EMPTY`, `OCCUPIED`, and `OVER_CAPACITY`; completing or expiring a training enrollment recomputes the personnel member's clearance flags. Each cascade independently mutates the affected resources, refreshing `updated_at` and incrementing `version` on each. The server applies these reconciliations automatically whenever their criteria are met, without requiring an explicit client request on the affected resource.

## 3. Business Logic & Workflows

### 3.1. Registering the Program: Investigators, Grants, and Personnel

An `IacucAdministrator` onboards the program's actors and funding. Registering an investigator records `full_name`, `email`, and `department`; the email must be unique across investigators, and the new investigator's `status` begins as `ACTIVE`, with `SUSPENDED` and `DEACTIVATED` rounding out the investigator lifecycle. Registering a grant captures `grant_number` (unique), the owning `investigator_id`, the award's `budget_total_cents` (zero or more), and the award end date `expires_on`. At registration, `budget_remaining_cents` is initialized to the full `budget_total_cents`, and thereafter it falls only as posted per-diem charges debit it; per-diem posting is forbidden once `expires_on` has passed. Registering a personnel member records `full_name`, a unique `email`, and the `role_on_protocols` the member will declare when attached to studies — one of `TECHNICIAN`, `CO_PI`, or `STUDENT` — with `status` beginning as `ACTIVE` (the personnel lifecycle also admits `SUSPENDED`).

Two computed booleans travel with every personnel record: `training_completed` and `occ_health_cleared`. Neither is set directly; both are derived from the member's enrollments, as described next.

### 3.2. Training and Occupational Health Clearance

A `TrainingCoordinator` enrolls personnel in the four required courses — `ANIMAL_HANDLING`, `ASEPTIC_TECHNIQUE`, `EUTHANASIA`, and `SPECIES_SPECIFIC`. Each enrollment is created with its `personnel_id` and `course_code`, and its `state` begins as `ENROLLED`. When the coordinator marks a course completed, the enrollment moves from `ENROLLED` to `COMPLETED`: `completed_at` is set to the current clock time, and `expires_at` becomes exactly 365 days after `completed_at` (until completion, `expires_at` is null). When the logical clock reaches `expires_at`, the enrollment moves from `COMPLETED` to `EXPIRED`, a terminal state. A personnel member's `training_completed` flag is recomputed on every completion and every expiry: it is true exactly when, for each of the four required course codes, the member holds an enrollment in `COMPLETED` whose `expires_at` is either unset or still in the future.

Occupational health runs in parallel under an `OccHealthNurse`. An occupational-health enrollment is created with a `personnel_id` and begins `ENROLLED`; clearance by the nurse moves it from `ENROLLED` to `CLEARED`, setting `cleared_at` to the current clock time and `expires_at` to 365 days later (null until cleared); when the clock reaches `expires_at`, the enrollment becomes `EXPIRED`, terminal. The member's `occ_health_cleared` flag is true exactly when at least one of their occupational-health enrollments stands `CLEARED` with an `expires_at` that is unset or still in the future, and it too is recomputed on every clearance and every expiry.

These two gates guard three operations later in this document. Attaching personnel to a protocol checks the member being attached; filing an adverse-event report checks the member named as `reported_by_personnel_id`; booking a procedure room checks the member named as `booked_by_personnel_id`. In all three cases the member must hold both `training_completed` and `occ_health_cleared`, and failure is rejected with `ERR_TRAINING_INCOMPLETE` (HTTP 422).

### 3.3. Protocol Authoring, Submission, and Committee Review

An `Investigator` authors a protocol by supplying `investigator_id`, `grant_id`, `title`, `species` (one of `MOUSE`, `RAT`, `RABBIT`, or `ZEBRAFISH`), `max_animals_justified` (a positive integer expressing the species-and-number justification ceiling), `pain_category` (USDA pain and distress category `B`, `C`, `D`, or `E`), and `review_path` (`DMR` for designated-member review or `FCR` for full-committee review). The server mints a human-readable `protocol_number` in the format IACUC-YYYY-NNNN. The protocol begins in `DRAFT`, with `animals_used_count` at zero and both `approved_at` and `expires_at` unset.

Submission is the investigator's own act: the `X-User-ID` must equal the protocol's `investigator_id` (else `ERR_NOT_OWNER`), the protocol must be in `DRAFT` (else `ERR_INVALID_STATE`), and the referenced grant must be solvent — `budget_remaining_cents` greater than zero and `expires_on` still ahead of the current clock time (else `ERR_GRANT_EXHAUSTED`, HTTP 402). A successful submission increments the protocol's `version` and moves it through `SUBMITTED` instantaneously: within the same request the system auto-routes on `review_path`. A `DMR` protocol lands in `DMR_REVIEW`, and the system creates one reviewer assignment of `reviewer_kind` `DESIGNATED_MEMBER` with `decision` `PENDING`. An `FCR` protocol lands in `FCR_REVIEW`, and the system creates three reviewer assignments of `reviewer_kind` `COMMITTEE_MEMBER`, each with `decision` `PENDING`. Every reviewer row records its `protocol_id` and the committee member's `reviewer_name`.

An `IacucAdministrator` then records the committee's verdict through a `decisions` payload. The `decisions` payload is a list of decision objects, and each decision object carries `reviewer_id` — the server-minted `id` of a reviewer assignment row, as listed by the protocol's reviewer listing after submission — and `decision`, one of `APPROVE`, `REQUIRE_MODIFICATIONS`, or `WITHHOLD`. Each `reviewer_id` is a body foreign key: a `reviewer_id` that matches no reviewer assignment row is rejected with `ERR_NOT_FOUND` per §2.6. The tally must fit the review path: for a `DMR` protocol the payload must carry exactly one decision for the single `DESIGNATED_MEMBER` row; for an `FCR` protocol it must carry decisions for all three `COMMITTEE_MEMBER` rows. A payload that does not form a valid tally for the protocol's path is rejected with `ERR_INVALID_VOTE_TALLY` (HTTP 422). The possible outcomes, each of which increments the protocol's `version`:

- Approval from `DMR_REVIEW` requires the designated member to vote `APPROVE`; approval from `FCR_REVIEW` requires at least two of the three committee members to vote `APPROVE` with no member voting `WITHHOLD`. Either approval sets `approved_at` to the current clock time, computes `expires_at` as exactly three years after `approved_at`, and moves the protocol to `APPROVED`.
- Return for modifications: a designated member voting `REQUIRE_MODIFICATIONS` sends a `DMR` protocol back to `DRAFT`, and under full committee a majority voting `REQUIRE_MODIFICATIONS` with no `WITHHOLD` does the same. In both paths, every reviewer row's `decision` is reset to `PENDING` for the next round.
- Withholding: a designated member voting `WITHHOLD`, or any single committee member voting `WITHHOLD`, moves the protocol to `WITHDRAWN`, a terminal state.

An approved protocol lives until its `expires_at`: when the logical clock reaches that instant the protocol moves from `APPROVED` to `EXPIRED`, which is terminal — no new animals may be added to it, and its existing animals must be transferred or euthanized.

Attaching staff is the investigator's prerogative and is performed with a payload containing `personnel_id`; the response carries `protocol_id` and `personnel_id`. The member being attached must clear both personnel gates (else `ERR_TRAINING_INCOMPLETE`), and each successful attachment increments the protocol's `version`.

### 3.4. Housing Operations: Cages, Animals, and Capacity

A `FacilityManager` creates cages by supplying `cage_barcode` (unique), `room_code`, `species`, `cage_kind` (`STANDARD`, or `BREEDING` for breeding pairs and their litters), `capacity_adults` (a positive integer; institutional policy caps adult occupancy at 5 for mice, 2 for rats, 1 for rabbits, and 20 for zebrafish), and the `protocol_id` the cage is billed to. A cage begins `EMPTY`. A manager may decommission a cage that stands `EMPTY`, moving it to `DECOMMISSIONED` — terminal — after which the cage is excluded from all future census and billing activity.

An `AnimalCareStaff` member adds an animal by supplying `animal_tag` (unique), `cage_id`, `protocol_id`, `species`, `date_of_birth`, `sex` (`M` or `F`), and optionally `litter_id`, which stays null for adults not born in-house. Animals begin `ALIVE`; the lifecycle also admits `RETIRED`, `EUTHANIZED`, and `TRANSFERRED_OUT`. Admission is refused — in the order fixed by §2.8 — when the protocol has reached its justified ceiling, when the protocol is not `APPROVED`, when species or protocol disagree between animal and cage or the cage is `DECOMMISSIONED`, or when the addition would overflow the cage. The ceiling rule counts `animals_used_count`, the number of animals on the protocol excluding only those `TRANSFERRED_OUT`, and its boundary is inclusive: once the count equals `max_animals_justified`, one more animal is refused with `ERR_ANIMAL_CAP_EXCEEDED` (HTTP 422). A protocol that is not `APPROVED` refuses admission with `ERR_PROTOCOL_NOT_APPROVED` (HTTP 409). A species or protocol mismatch, or a decommissioned cage, produces `ERR_CAGE_MISMATCH` (HTTP 422); an overflowing placement produces `ERR_CAGE_OVER_CAPACITY` (HTTP 422).

Cage capacity is computed as effective occupancy: the number of `ALIVE` animals in the cage with no `litter_id` — the adults — plus the number of `ALIVE` pups whose age exceeds 21 days. A nursing pup is exempt from the count through its twenty-first day of age and begins counting on day twenty-two. Whenever effective occupancy exceeds `capacity_adults` the cage becomes `OVER_CAPACITY` and accepts no further animal additions; whenever effective occupancy falls to zero the cage becomes `EMPTY`, even if nursing pups still exempt from the count are physically present in it; otherwise a cage holding animals reads `OCCUPIED` — except that a protocol suspension forces `OVER_CAPACITY` regardless of headcount. Placing the first animal into an `EMPTY` cage flips it to `OCCUPIED` and requires that the cage's protocol and species match the animal's; removing the last `ALIVE` animal returns a cage to `EMPTY`. Every occupancy recomputation increments the affected cage's `version`.

Four lifecycle actions follow, all available to `AnimalCareStaff`, with euthanasia additionally available to the `AttendingVeterinarian`. Retirement moves an animal from `ALIVE` to `RETIRED`. Euthanasia moves an animal from `ALIVE` to `EUTHANIZED`, or from `RETIRED` to `EUTHANIZED`. Transfer-out moves an animal from `ALIVE` to `TRANSFERRED_OUT` and recomputes the protocol's `animals_used_count` downward, since transferred-out animals leave the justified-count tally. A cage-to-cage transfer keeps the animal `ALIVE` and reassigns its `cage_id` to the `target_cage_id` in the request; the target cage must pass the same species-and-protocol consistency and capacity checks, and both source and target cages have their occupancy recomputed and their `version` incremented. Retirement and euthanasia recompute the housing cage's occupancy but leave `animals_used_count` untouched, because only `TRANSFERRED_OUT` animals exit that count.

### 3.5. Breeding Colonies and Litters

On a breeding cage, an `AnimalCareStaff` member records a new litter by supplying `cage_id`, `protocol_id`, `born_on`, and `pup_count` (a positive integer). The system creates `pup_count` pup animal rows linked to the litter through `litter_id`; under the nursing exemption these pups do not count toward cage capacity for their first 21 days of age. The litter's `state` begins as `NURSING`, with `weaned_count` at zero.

Weaning becomes available once the logical clock reaches `born_on` plus 21 days; an earlier attempt is rejected with `ERR_LITTER_TOO_YOUNG` (HTTP 422), and a litter no longer `NURSING` rejects the attempt with `ERR_INVALID_STATE`. Weaning moves the litter from `NURSING` to `WEANED` and sets `weaned_count` to the full `pup_count`; every pup's `cage_id` is reassigned to the standard cages named in the request's `target_cage_ids`, each target cage must absorb its newcomers within `capacity_adults` (else `ERR_CAGE_OVER_CAPACITY`), and the source and target cages are all recomputed. A `WEANED` litter may later be closed, moving to `CLOSED`, which is terminal.

Colony management reads a computed productivity score per cage, exposed as a read capability returning `cage_id`, `score`, `weaned_litters`, `weaned_pups`, and `nonproductive_days`. The score is three times the number of the cage's litters that have reached `WEANED` or `CLOSED`, plus one-half times the total pups weaned across those litters, minus five-hundredths times the nonproductive days, floored at zero, and rounded half-up to two decimal places. Nonproductive days are the days since the cage became `OCCUPIED` on which no litter in the cage stood `NURSING` or `WEANED`.

### 3.6. The Daily Census

Each day, an `AnimalCareStaff` member files a physical census for a cage, supplying `cage_id`, `census_date` (the calendar day of the count, at midnight UTC), and `physical_count` (zero or more). The server computes `system_count` — the number of animals whose `cage_id` is this cage and whose `status` is `ALIVE` on that census date — and `discrepancy`, the physical count minus the system count. A nonzero discrepancy has teeth: while any census record covering a day inside a billing run's period carries a `discrepancy` other than zero, provisional computation for that run is refused, as the next subsection describes.

### 3.7. Per-Diem Billing and Grant Posting

A `BillingCoordinator` opens a billing run by supplying `period_start`, the first billable day (inclusive, midnight UTC), and `period_end`, the last billable day (exclusive, midnight UTC, and it must fall after `period_start`). The run's `state` begins as `DRAFT` with `hold_reason` null, and its lifecycle runs `DRAFT` → `PROVISIONAL` → `FINALIZED` → `POSTED`, with `VOIDED` reachable from either `DRAFT` or `PROVISIONAL`.

Provisional computation is census-gated. If any census record in the run's period carries a nonzero `discrepancy`, the attempt is rejected with `ERR_CENSUS_DISCREPANCY` (HTTP 422), the reason is recorded in the run's `hold_reason`, and the run remains `DRAFT`. Otherwise the run advances to `PROVISIONAL` and the system creates one per-diem charge of `variant` `PROVISIONAL` for every cage occupied during the period, each charge linked by `billing_run_id`, `cage_id`, `protocol_id`, and the `grant_id` to be debited at posting.

The provisional computation is the cage-day model. A cage accrues one billable cage-day, accumulated into `cage_days`, for each calendar day from `period_start` up to but not including `period_end` on which it held at least one `ALIVE` animal, regardless of headcount. The daily `rate_cents` is fixed by species: 125 for mice, 400 for rabbits, 40 for zebrafish. Rat cages are tiered by the ages of the rats present each day: a rat younger than 21 days bills at the pup rate of 75, a rat older than 365 days bills at the aged rate of 210, and any other rat bills at the adult rate of 150; a cage housing rats of mixed ages bills the whole day at the highest tier present among its rats. Each cage's `amount_cents` is the sum over its billable days of that day's rate, with each day's charge rounded half-up to integer cents before the days are summed.

Finalization moves the run from `PROVISIONAL` to `FINALIZED` and recomputes every charge as `variant` `FINAL` under the reconciled-census model: identical to the provisional model except that a day counts only when a reconciled census — a census record whose `discrepancy` is zero — confirms occupancy for that day, and animals that reached `RETIRED` or `EUTHANIZED` before `period_end` are excluded from the day's headcount on and after their status-change date. The two variants therefore diverge precisely when a mid-period retirement or euthanasia occurred. Finalization is OCC-guarded: the request must carry `expected_billing_run_version` matching the run's current `version`, and a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412), protecting the coordinator from finalizing a run whose contents have moved since they last read it.

Posting moves the run from `FINALIZED` to `POSTED`, which is terminal, and debits each grant's `budget_remaining_cents` by the sum of that grant's charge amounts. Posting is solvency-gated per charge: every charge's `amount_cents` must fit within its grant's `budget_remaining_cents`, and the grant's `expires_on` must fall on or after `period_end`; any violation is rejected with `ERR_GRANT_INSOLVENT` (HTTP 402).

Voiding is available from `DRAFT`, where no charges were ever created, and from `PROVISIONAL`, where voiding deletes the provisional charge rows; `VOIDED` is terminal in both cases.

### 3.8. Adverse Events, Deviations, and Protocol Suspension

An `AnimalCareStaff` member or the `AttendingVeterinarian` files an adverse-condition report by supplying `protocol_id`, `animal_id`, `reported_by_personnel_id`, `severity` (one of `MINOR`, `MODERATE`, `SEVERE`, or `MORBUND`), and a clinical `description`. The protocol must be `APPROVED` (else `ERR_PROTOCOL_NOT_APPROVED`), and the reporting member must clear both personnel gates (else `ERR_TRAINING_INCOMPLETE`). The report's `state` begins as `OPEN`, with `reported_at` set to the current clock time.

The veterinarian begins treatment, moving the report from `OPEN` to `UNDER_TREATMENT`. Resolution is deadline-bound: a report in `UNDER_TREATMENT` may be resolved — moving to `RESOLVED` with `resolved_at` set — only while the clock stands at or before `reported_at` plus 72 hours; a resolve attempted after that deadline is rejected with `ERR_RESOLUTION_OVERDUE` (HTTP 422), and the report must be escalated first. Escalation moves a report from `OPEN` to `ESCALATED`, or from `UNDER_TREATMENT` to `ESCALATED`, and the system also escalates an `UNDER_TREATMENT` report automatically when the 72-hour deadline is breached. Escalation carries a regulatory cascade: when the report's `severity` is `SEVERE` or `MORBUND`, the system automatically files a protocol deviation of `seriousness` `SERIOUS` against the same protocol. An `ESCALATED` report can still be resolved — the move from `ESCALATED` to `RESOLVED` carries no deadline — and `RESOLVED` is terminal.

Deviations may also be reported directly by an `AnimalCareStaff` member, the `AttendingVeterinarian`, or an `Investigator`, supplying `protocol_id`, `reported_by_personnel_id`, `description`, and `seriousness` (`MINOR`, or `SERIOUS` for deviations reportable to OLAW); the deviation's `state` begins as `REPORTED`. An `IacucAdministrator` begins committee review, moving it from `REPORTED` to `UNDER_REVIEW`. From `UNDER_REVIEW` there are exactly two exits. Closing is reserved for `MINOR` deviations — closing a `SERIOUS` deviation is rejected with `ERR_SERIOUS_DEVIATION_NOT_CLOSABLE` (HTTP 422) — and the closer must not be the reporter, per §2.10. Imposing suspension moves the deviation to `SUSPENSION_IMPOSED` and cascades: the protocol moves from `APPROVED` to `SUSPENDED`, and that protocol suspension in turn cascades to cages and adverse-event reports as described below. `CLOSED` and `SUSPENSION_IMPOSED` are both terminal for the deviation.

An administrator may also suspend an approved protocol directly, provided some deviation on that protocol already stands in `SUSPENSION_IMPOSED` — the causal chain always runs from deviation review to suspension — and provided the request carries `expected_protocol_version` matching the protocol's current `version` (a mismatch is `ERR_STALE_VERSION`, HTTP 412). Suspension cascades broadly: every cage billed to the protocol that stands `OCCUPIED` becomes `OVER_CAPACITY`, frozen against any new animal additions, and every adverse-event report on the protocol in `OPEN` or `UNDER_TREATMENT` becomes `ESCALATED`. Reinstatement requires every deviation on the protocol to stand in `CLOSED` or `SUSPENSION_IMPOSED`; it returns the protocol from `SUSPENDED` to `APPROVED` and recounts each frozen cage, returning those whose effective occupancy is within `capacity_adults` to `OCCUPIED`.

### 3.9. Facility Inspections and Procedure-Room Scheduling

Semiannual oversight is scheduled by an `IacucAdministrator`. An inspection is created with `inspection_kind` — `FACILITY` for the semiannual facility inspection or `PROGRAM_REVIEW` for the semiannual program review — plus `scheduled_for` and an optional `deficiency_count` that defaults to zero. The server computes `due_by` as the completion time of the most recent `COMPLETED` inspection of the same kind plus 180 days; when no inspection of that kind has ever been completed, `due_by` equals the new inspection's own `scheduled_for`, so the first cycle is free. The inspection's `state` begins as `SCHEDULED`. Completing an inspection records `completed_at` and the final `deficiency_count`: completion at or before `due_by` moves the inspection to `COMPLETED` — the boundary is inclusive, so completion exactly at `due_by` is on time — while completion even one second past `due_by` moves the inspection to `LAPSED` and surfaces `ERR_INSPECTION_LAPSED` (HTTP 422). If the logical clock passes `due_by` while an inspection still stands `SCHEDULED`, the inspection lapses automatically. Both `COMPLETED` and `LAPSED` are terminal.

Procedure rooms are booked by an `AnimalCareStaff` member or the `AttendingVeterinarian` with `room_code`, `protocol_id`, `booked_by_personnel_id`, `start_at`, and `end_at`; the booking occupies the half-open interval from `start_at` up to but not including `end_at`, and its `state` begins as `CONFIRMED`. The booking member must clear both personnel gates (else `ERR_TRAINING_INCOMPLETE`), the protocol must be `APPROVED` (else `ERR_PROTOCOL_NOT_APPROVED`), and `start_at` must not precede the current logical clock time (else `ERR_BOOKING_IN_PAST`, HTTP 422). Conflict detection adds a thirty-minute turnover buffer: each booking effectively occupies its interval extended thirty minutes past its end, so a new booking conflicts with an existing `CONFIRMED` booking in the same room whenever the new `start_at` falls earlier than thirty minutes after the existing booking's `end_at` and, simultaneously, the existing booking's start falls earlier than thirty minutes after the new booking's `end_at`. Such a conflict is rejected with `ERR_ROOM_CONFLICT` (HTTP 409), while a new booking starting exactly thirty minutes after an existing booking ends is permitted. Cancellation by an `AnimalCareStaff` member or the `AttendingVeterinarian` moves the booking from `CONFIRMED` to `CANCELLED`, terminal, and removes it from the conflict candidate set.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; this covers registering investigators, grants, personnel, enrollments, protocols, cages, animals, litters, census records, billing runs, inspections, adverse-event reports, and room bookings, as well as attaching personnel to a protocol. Operations that act on an existing resource without creating a new one — state transitions, decision recording, clock setting, and all reads — return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/iacuc/_clock/set_current_utc` | Set the server's logical clock | IacucAdministrator |
| POST | `/iacuc/investigators` | Register an investigator | IacucAdministrator |
| GET | `/iacuc/investigators/{id}` | Fetch investigator | IacucAdministrator, Investigator |
| POST | `/iacuc/grants` | Register a grant | IacucAdministrator |
| GET | `/iacuc/grants/{id}` | Fetch grant (includes computed budget remaining) | IacucAdministrator, Investigator, BillingCoordinator |
| GET | `/iacuc/investigators/{id}/grants` | List grants for an investigator | IacucAdministrator, Investigator |
| POST | `/iacuc/personnel` | Register personnel | IacucAdministrator |
| GET | `/iacuc/personnel/{id}` | Fetch personnel (includes computed clearance flags) | IacucAdministrator, TrainingCoordinator, OccHealthNurse, AttendingVeterinarian |
| POST | `/iacuc/training-enrollments` | Enroll personnel in a course | TrainingCoordinator |
| GET | `/iacuc/personnel/{id}/training-enrollments` | List training enrollments for personnel | TrainingCoordinator, IacucAdministrator |
| POST | `/iacuc/training-enrollments/{id}/complete` | Mark a course completed | TrainingCoordinator |
| POST | `/iacuc/occ-health-enrollments` | Enroll personnel in occupational health | OccHealthNurse |
| GET | `/iacuc/personnel/{id}/occ-health-enrollments` | List occ-health enrollments for personnel | OccHealthNurse, IacucAdministrator |
| POST | `/iacuc/occ-health-enrollments/{id}/clear` | Clear personnel for animal contact | OccHealthNurse |
| POST | `/iacuc/protocols` | Create protocol in DRAFT | Investigator |
| GET | `/iacuc/protocols/{id}` | Fetch protocol | IacucAdministrator, Investigator, AttendingVeterinarian, AnimalCareStaff, BillingCoordinator |
| GET | `/iacuc/investigators/{id}/protocols` | List protocols for an investigator | IacucAdministrator, Investigator |
| GET | `/iacuc/grants/{id}/protocols` | List protocols billed to a grant | IacucAdministrator, BillingCoordinator |
| POST | `/iacuc/protocols/{id}/submit` | Submit protocol; auto-routes to the configured review path | Investigator |
| POST | `/iacuc/protocols/{id}/review-decisions` | Record reviewer decision(s) | IacucAdministrator |
| GET | `/iacuc/protocols/{id}/reviewers` | List reviewer assignments | IacucAdministrator |
| POST | `/iacuc/protocols/{id}/suspend` | Suspend an approved protocol (OCC-guarded) | IacucAdministrator |
| POST | `/iacuc/protocols/{id}/reinstate` | Reinstate a suspended protocol | IacucAdministrator |
| POST | `/iacuc/protocols/{id}/personnel` | Attach personnel to a protocol (training/occ-health gated) | Investigator |
| POST | `/iacuc/cages` | Create a cage | FacilityManager |
| GET | `/iacuc/cages/{id}` | Fetch cage | FacilityManager, AnimalCareStaff, BillingCoordinator, IacucAdministrator |
| GET | `/iacuc/protocols/{id}/cages` | List cages billed to a protocol | AnimalCareStaff, IacucAdministrator, BillingCoordinator |
| POST | `/iacuc/cages/{id}/decommission` | Decommission an empty cage | FacilityManager |
| GET | `/iacuc/cages/{id}/productivity` | Computed breeding productivity score | AnimalCareStaff, FacilityManager |
| POST | `/iacuc/animals` | Add an animal to a cage | AnimalCareStaff |
| GET | `/iacuc/animals/{id}` | Fetch animal | AnimalCareStaff, AttendingVeterinarian, IacucAdministrator |
| GET | `/iacuc/cages/{id}/animals` | List animals in a cage | AnimalCareStaff, AttendingVeterinarian, IacucAdministrator |
| GET | `/iacuc/protocols/{id}/animals` | List animals on a protocol | AnimalCareStaff, IacucAdministrator, Investigator |
| POST | `/iacuc/animals/{id}/transfer` | Move animal to another cage | AnimalCareStaff |
| POST | `/iacuc/animals/{id}/retire` | Retire an animal | AnimalCareStaff |
| POST | `/iacuc/animals/{id}/transfer-out` | Transfer an animal out of the institution | AnimalCareStaff |
| POST | `/iacuc/animals/{id}/euthanize` | Euthanize an animal | AnimalCareStaff, AttendingVeterinarian |
| POST | `/iacuc/litters` | Record a litter born in a breeding cage | AnimalCareStaff |
| GET | `/iacuc/cages/{id}/litters` | List litters in a cage | AnimalCareStaff, FacilityManager |
| GET | `/iacuc/litters/{id}` | Fetch a litter | AnimalCareStaff, FacilityManager |
| GET | `/iacuc/litters/{id}/animals` | List pup animals of a litter | AnimalCareStaff |
| GET | `/iacuc/protocols/{id}/litters` | List litters under a protocol | AnimalCareStaff, IacucAdministrator |
| POST | `/iacuc/litters/{id}/wean` | Wean a litter into target standard cages | AnimalCareStaff |
| POST | `/iacuc/litters/{id}/close` | Close a weaned litter record | AnimalCareStaff |
| POST | `/iacuc/census-records` | File a daily physical census for a cage | AnimalCareStaff |
| GET | `/iacuc/cages/{id}/census-records` | List census records for a cage | AnimalCareStaff, BillingCoordinator |
| POST | `/iacuc/billing-runs` | Create a billing run for a period | BillingCoordinator |
| GET | `/iacuc/billing-runs/{id}` | Fetch billing run | BillingCoordinator, IacucAdministrator |
| GET | `/iacuc/billing-runs/{id}/charges` | List per-diem charges of a run | BillingCoordinator, IacucAdministrator |
| GET | `/iacuc/grants/{id}/charges` | List charges billed to a grant | BillingCoordinator, IacucAdministrator |
| GET | `/iacuc/cages/{id}/charges` | List per-diem charges for a cage | BillingCoordinator, IacucAdministrator |
| GET | `/iacuc/protocols/{id}/charges` | List per-diem charges for a protocol | BillingCoordinator, IacucAdministrator |
| POST | `/iacuc/billing-runs/{id}/compute-provisional` | Compute provisional per-diem charges (census-gated) | BillingCoordinator |
| POST | `/iacuc/billing-runs/{id}/finalize` | Finalize charges from reconciled census (OCC-guarded) | BillingCoordinator |
| POST | `/iacuc/billing-runs/{id}/post` | Post charges to grants (solvency-gated) | BillingCoordinator |
| POST | `/iacuc/billing-runs/{id}/void` | Void a draft or provisional run | BillingCoordinator |
| POST | `/iacuc/inspections` | Schedule a semiannual facility inspection or program review | IacucAdministrator |
| GET | `/iacuc/inspections/{id}` | Fetch inspection | IacucAdministrator, FacilityManager |
| POST | `/iacuc/inspections/{id}/complete` | Complete an inspection on time (else LAPSED) | IacucAdministrator |
| POST | `/iacuc/adverse-events` | File an adverse-condition report | AnimalCareStaff, AttendingVeterinarian |
| GET | `/iacuc/protocols/{id}/adverse-events` | List adverse events on a protocol | AttendingVeterinarian, IacucAdministrator |
| GET | `/iacuc/animals/{id}/adverse-events` | List adverse events for an animal | AttendingVeterinarian, IacucAdministrator |
| GET | `/iacuc/personnel/{id}/adverse-events` | List adverse events reported by a personnel member | AttendingVeterinarian, IacucAdministrator |
| GET | `/iacuc/personnel/{id}/protocol-deviations` | List deviations reported by a personnel member | IacucAdministrator |
| POST | `/iacuc/adverse-events/{id}/begin-treatment` | Begin veterinary treatment | AttendingVeterinarian |
| POST | `/iacuc/adverse-events/{id}/escalate` | Escalate; SEVERE/MORBUND auto-files a SERIOUS deviation | AttendingVeterinarian |
| POST | `/iacuc/adverse-events/{id}/resolve` | Resolve an adverse event (72-hour deadline rule) | AttendingVeterinarian |
| POST | `/iacuc/protocol-deviations` | Report a protocol deviation | AnimalCareStaff, AttendingVeterinarian, Investigator |
| GET | `/iacuc/protocols/{id}/deviations` | List deviations on a protocol | IacucAdministrator, AttendingVeterinarian |
| POST | `/iacuc/protocol-deviations/{id}/begin-review` | Begin committee review of a deviation | IacucAdministrator |
| POST | `/iacuc/protocol-deviations/{id}/close` | Close a MINOR deviation under review | IacucAdministrator |
| POST | `/iacuc/protocol-deviations/{id}/impose-suspension` | Impose suspension from a deviation under review (cascades) | IacucAdministrator |
| POST | `/iacuc/room-bookings` | Book a procedure room (conflict + training gated) | AnimalCareStaff, AttendingVeterinarian |
| GET | `/iacuc/protocols/{id}/room-bookings` | List bookings for a protocol | AnimalCareStaff, AttendingVeterinarian, IacucAdministrator |
| GET | `/iacuc/personnel/{id}/room-bookings` | List bookings made by a personnel member | AnimalCareStaff, IacucAdministrator |
| POST | `/iacuc/room-bookings/{id}/cancel` | Cancel a booking | AnimalCareStaff, AttendingVeterinarian |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_NOT_OWNER` | 403 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_TRAINING_INCOMPLETE` | 422 |
| `ERR_ANIMAL_CAP_EXCEEDED` | 422 |
| `ERR_PROTOCOL_NOT_APPROVED` | 409 |
| `ERR_CAGE_MISMATCH` | 422 |
| `ERR_CAGE_OVER_CAPACITY` | 422 |
| `ERR_ROOM_CONFLICT` | 409 |
| `ERR_LITTER_TOO_YOUNG` | 422 |
| `ERR_RESOLUTION_OVERDUE` | 422 |
| `ERR_INSPECTION_LAPSED` | 422 |
| `ERR_CENSUS_DISCREPANCY` | 422 |
| `ERR_GRANT_INSOLVENT` | 402 |
| `ERR_GRANT_EXHAUSTED` | 402 |
| `ERR_DUPLICATE` | 409 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_SERIOUS_DEVIATION_NOT_CLOSABLE` | 422 |
| `ERR_INVALID_VOTE_TALLY` | 422 |
| `ERR_BOOKING_IN_PAST` | 422 |
