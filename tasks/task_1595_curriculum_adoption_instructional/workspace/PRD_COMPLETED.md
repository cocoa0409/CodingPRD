# Curriculum Adoption API — Product Requirements Document

## 1. Introduction

A school district's curriculum office carries a multi-year statutory obligation: select instructional materials subject by subject, demonstrate that each candidate covers the state framework's standards, pilot the finalists in real classrooms under a structured teacher rubric, expose the slate to public scrutiny, secure a board of education decision, and then purchase and deliver the adopted materials under formal procurement rules — all while keeping an audit trail sturdy enough to survive a community reconsideration challenge. This document specifies the Curriculum Adoption API, the system of record for that entire obligation, from the first framework registration to the final warehouse shipment and the replacement forecast that starts the cycle over again.

The API is built around three commitments. First, due process: public review windows, challenge filing deadlines, committee quorum, and a single appeal per case are enforced by the server rather than by policy memos. Second, segregation of duties: the teacher who requests a supplemental purchase may not approve it, and the community member who files a challenge may not vote on it. Third, conservation: two ledgers — one fiscal, one physical — guarantee that every appropriated dollar and every received textbook is accounted for at all times, with derived balances that must always reconcile against their event histories. Nine operator roles interact with the system, and all calendar-sensitive rules read a district-controlled logical clock rather than wall-clock time. Section 2 defines the global contracts every endpoint obeys, Section 3 narrates the business workflows in which those contracts come alive, Section 4 summarizes the endpoint surface, and Section 5 catalogues the error identifiers referenced throughout.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two authentication headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, declaring the capacity in which that operator acts. The system recognizes exactly nine roles, spelled precisely as follows: `DistrictAdmin`, `CurriculumDirector`, `InstructionalSpecialist`, `BoardSecretary`, `ProcurementOfficer`, `WarehouseManager`, `Teacher`, `CommitteeMember`, and `CommunityMember`. A request with a missing header, or whose declared role is not one of these nine, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). A request whose role is not authorized for the target endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).

The roles divide the work of the district as follows. A `DistrictAdmin` maintains curriculum frameworks, posts budget appropriations, and controls the logical clock. A `CurriculumDirector` creates adoption cycles, submits materials, plans and drives pilots, and shepherds challenge cases through their administrative stages. An `InstructionalSpecialist` vets materials, maintains standards-alignment mappings, vets supplemental requests, and drives the early cycle stages. A `BoardSecretary` opens and closes the public review window and records board decisions. A `ProcurementOfficer` manages publisher quotes, evaluation, contract awards, purchase orders, and payments. A `WarehouseManager` posts publisher receipts and runs classroom distribution. A `Teacher` submits pilot rubric reviews and files supplemental material requests. A `CommitteeMember` casts reconsideration votes and issues committee decisions. A `CommunityMember` files challenges and appeals their own cases.

For every one of these nine roles, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity; the server never compares it against any resource's `id`. The identifier is recorded on resources at the moment of action — as `requester_user_id` when a `Teacher` files a supplemental request, as `teacher_user_id` when a `Teacher` submits a review, as `approver_user_id` when an `InstructionalSpecialist` approves a supplemental request, as `filer_user_id` when a `CommunityMember` files a challenge, and as `voter_user_id` when a `CommitteeMember` casts a vote — and those recorded values are what later ownership and segregation-of-duties checks compare against. Two user-level ownership rules exist beyond role checks: withdrawing a review requires the requesting operator to be the teacher recorded on that review, and appealing a challenge requires the requesting operator to be the community member who filed it; violations are rejected with `ERR_INSUFFICIENT_PERMISSIONS`.
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

- The `api_request_id` is a server-generated unique identifier for the request: the prefix `req_` followed by twenty random alphanumeric characters.
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
- The `message` provides a human-readable explanation of what went wrong; its exact wording is not contractual — only the `error_id` and the HTTP status identify the error. A request to an undefined path is rejected with `ERR_NOT_FOUND` (HTTP 404), and a request using an unsupported method on a defined path with `ERR_VALIDATION` (HTTP 405); both render in this same error envelope.

---

### 2.3. Pagination

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10 when omitted, and any value below 1 or above 100 is rejected with `ERR_INVALID_PAGINATION_PARAMETERS` (HTTP 400). The `offset` parameter states how many items to skip; it defaults to 0, and a negative value is likewise rejected with `ERR_INVALID_PAGINATION_PARAMETERS`. A `limit` or `offset` value that does not parse as an integer is rejected the same way. These bounds are enforced on every list endpoint.

Unless otherwise specified, every list endpoint returns its resources sorted by creation timestamp (`created_at`) in ascending order; resources created at the same instant keep their creation (insertion) order.

Paginated list responses carry four pagination fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more` — the last being true exactly when `offset` plus the number of items returned in the page is less than `total_count`.

### 2.4. The Logical Clock and Calendar Windows

The server maintains a district-controlled logical clock. Before any call to the clock-setting endpoint (`/_clock/set_current_utc`, restricted to `DistrictAdmin`), the logical clock reads exactly 2026-08-01T00:00:00Z and must never fall back to wall-clock time. A `DistrictAdmin` advances the clock by supplying a `to_iso8601` instant — any parseable ISO 8601 instant is accepted, including one earlier than the current reading, and a value without an offset is read as UTC — and the response (HTTP 200) echoes the new reading as `current_utc`.

Every window, deadline, and recorded instant in this document reads the logical clock: pilot activation dates, the close of a public review window, the ninety-day challenge filing window, the fourteen-day appeal window, and the timestamps stamped onto resources as they move (`submitted_at` on reviews and quotes, `filed_at` and `decided_at` on challenges, `adopted_at` on materials, `approved_at` on supplemental requests, and the public review stamps on cycles).

### 2.5. Common Resource Properties

Every primary resource — frameworks, cycles, materials, alignment mappings, pilots, reviews, quotes, purchase orders, inventory lots, distribution orders, supplemental requests, challenge cases, and budget ledgers — carries a standard set of system-managed fields:

- `id` (string): a server-minted UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp reading the logical clock (§2.4), set when the resource is created; a whole-second reading renders without a fractional part (e.g. `2026-08-01T00:00:00Z`), a sub-second reading with three fractional digits.
- `updated_at` (string): an ISO 8601 UTC timestamp rendered like `created_at`, refreshed on every mutation of the resource — state transitions and system recomputes of derived fields alike.
- `version` (integer): a system-managed integer that starts at 1 on creation and increments by exactly one on every state transition and every operator-driven write of the resource's own fields; system recomputes of computed fields refresh only `updated_at` and leave `version` untouched (§2.9).

One exception exists: a committee vote is immutable once cast. A vote record carries only `id` and `created_at`; both `updated_at` and `version` are absent from it.

Across every serializer, a field that has no value — an unset `isbn`, a null `provisional_composite`, an undecided challenge's `decision`, an unopened cycle's public review stamps — is present with a JSON `null` value rather than omitted. Client-supplied values for system-managed fields (`id`, `created_at`, `updated_at`, `version`, and any server-stamped status or computed field) are ignored, and request-body fields an endpoint does not define are likewise ignored; neither is rejected.

### 2.6. Money, Precision, and Rounding Discipline

All monetary arithmetic — quote evaluation totals, purchase order totals, ledger balances, and budget forecasts — is performed in exact decimal arithmetic, and every final monetary value is rounded half-up to exactly 2 decimal places and returned as a number. Composite review scores are rounded half-up to 2 decimal places; the pilot participation rate is rounded half-up to 4 decimal places; inventory figures are whole units.

Two calculations pin their rounding order more tightly and are specified where they live: the bundled pricing total rounds each line to cents before any discount or summation (§3.5), and the budget forecast rounds its base before selecting a contingency tier (§3.10). The best-value score is assembled at full precision with no intermediate rounding and rounded half-up to 2 decimal places only at the end (§3.5).

### 2.7. The Request Validation Cascade and Nested Path Resolution

Every request is evaluated against an ordered cascade of checks; a rejection at an earlier tier masks every later tier. The tiers run in this order:

1. Authentication: the `X-User-ID` and `X-User-Role` headers are present and the role is one of the nine declared roles (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`).
2. Authorization: the caller's role is permitted on the endpoint, and the two user-level ownership rules hold (`ERR_INSUFFICIENT_PERMISSIONS`).
3. Existence: identifiers in the path are validated in left-to-right order, then identifiers referenced in the body — `framework_id`, `cycle_id`, `material_id`, `quote_id`, and `target_id` interpreted per `target_type` — are resolved (`ERR_NOT_FOUND`; the error message names the resource type that was not found).
4. Request shape: the body is a JSON object, required fields are present (a blank string does not satisfy a required string field), enum values are in range, integer quantities and counts meet their bounds, prices are non-negative, payment and appropriation amounts are positive, an end date follows its start date, and pagination parameters are in range (`ERR_VALIDATION`, or `ERR_INVALID_PAGINATION_PARAMETERS` on list endpoints).
5. State: the target entity — and any cross-entity gate, such as the cycle status required for pilot activation — is in the required from-state (`ERR_INVALID_STATE`, `ERR_UNRESOLVED_PILOTS`, `ERR_OPEN_WORK_REMAINS`).
6. Stale version: the optimistic-concurrency guard on the two cycle-scoped writes, evaluated only after the entity's own state preconditions have passed and before any business rule (`ERR_STALE_CYCLE_VERSION`).
7. Temporal windows: deadline and window rules (`ERR_PILOT_NOT_STARTED`, `ERR_PUBLIC_REVIEW_NOT_CLOSED`, `ERR_CHALLENGE_WINDOW_CLOSED`, `ERR_APPEAL_WINDOW_CLOSED`).
8. Interval occupation: pilot window overlaps and the public-review clear-gap rule (`ERR_PILOT_WINDOW_CONFLICT`, `ERR_PUBLIC_REVIEW_WINDOW_CONFLICT`).
9. Safety: frozen materials and segregation of duties (`ERR_MATERIAL_FROZEN`, `ERR_SEGREGATION_OF_DUTIES`).
10. Domain thresholds and structural constraints (`ERR_ALIGNMENT_COVERAGE_BELOW_THRESHOLD`, `ERR_NO_VETTED_MATERIALS`, `ERR_COMPOSITE_BELOW_THRESHOLD`, `ERR_PARTICIPATION_BELOW_FLOOR`, `ERR_BID_RULE_NOT_SATISFIED`, `ERR_QUOTE_NOT_AWARD_WINNER`, `ERR_QUOTE_NOT_SELECTED`, `ERR_QUOTE_MATERIAL_MISMATCH`, `ERR_INSUFFICIENT_INVENTORY`, `ERR_OVER_RECEIPT`, `ERR_PO_NOT_CLOSABLE`, `ERR_PAYMENT_EXCEEDS_BALANCE`, `ERR_QUORUM_NOT_MET`, `ERR_DUPLICATE_VOTE`, `ERR_DUPLICATE_REVIEW`, `ERR_OPEN_CHALLENGE_EXISTS`).
11. Referential integrity: framework match on cycle creation, adoption state on distribution creation, challenge target eligibility (`ERR_FRAMEWORK_MISMATCH`, `ERR_MATERIAL_NOT_ADOPTED`, `ERR_CHALLENGE_TARGET_INVALID`).
12. Fiscal envelope: funds-sufficiency checks run last (`ERR_BUDGET_ENVELOPE_EXCEEDED`).

Path identifiers — named `frameworkId`, `cycleId`, `materialId`, `pilotId`, `reviewId`, `quoteId`, `poId`, `doId`, `srId`, `ccId`, or the generic `id` depending on the endpoint — are validated strictly left to right: a request addressing a nested resource under a non-existent parent is rejected for the parent before the child is even looked up.

Every `/transitions` endpoint of §4 drives its entity's state machine through a required `to_state` field whose accepted values form an endpoint-scoped enum, checked at the request-shape tier: a request missing `to_state`, carrying a non-string value, or naming a state outside the endpoint's accepted set is rejected with `ERR_VALIDATION`. The accepted sets are: the adoption cycle transitions endpoint accepts `ALIGNMENT_REVIEW`, `DRAFT`, `PILOT_OPEN`, `SCORING`, `PUBLIC_REVIEW`, `BOARD_PENDING`, `ACTIVE`, or `SUNSET`; the material transitions endpoint accepts `VETTED` or `REJECTED`; the pilot transitions endpoint accepts `ACTIVE`, `CLOSED`, or `CANCELLED`; the quote transitions endpoint accepts `UNDER_EVALUATION`, `CLARIFICATION_REQUESTED`, or `WITHDRAWN`; the purchase order transitions endpoint accepts only `CLOSED`; the distribution order transitions endpoint accepts `APPROVED`, `BACKORDERED`, `SHIPPED`, `RECEIVED`, or `CANCELLED`; the supplemental request transitions endpoint accepts `VETTING`, `APPROVED`, or `DENIED`; and the challenge case transitions endpoint accepts `SCREENING`, `COMMITTEE_REVIEW`, `HEARING`, `DECIDED`, `APPEALED`, or `CLOSED`. Values outside these sets — initial states, and statuses an entity reaches only through another operation or an automatic cascade (a material's `PILOT_CANDIDATE` and `ADOPTED`; a cycle's `ADOPTED`, `NOT_ADOPTED`, `PROCURING`, and `DISTRIBUTING`; a quote's `SELECTED`, `REJECTED`, and `SUPERSEDED`; a supplemental request's `UNDER_CHALLENGE`, `REAFFIRMED`, and `REVOKED`) — are not valid `to_state` values on the transitions endpoint and fail at the shape tier, not the state tier. An accepted `to_state` naming a move that is not legal from the entity's current state then fails the state check with `ERR_INVALID_STATE`, and the move's further preconditions produce the errors §3 names for them. On the two transitions endpoints shared by several roles — cycle transitions and challenge transitions — each accepted `to_state` is further restricted to the single role §3 assigns to that move (for example `PILOT_OPEN` to `InstructionalSpecialist`, `PUBLIC_REVIEW` and `BOARD_PENDING` to `BoardSecretary`, `DECIDED` to `CommitteeMember`, `APPEALED` to `CommunityMember`); a caller whose role does not match the requested `to_state` is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403) after the `to_state` shape check and before the state check.

### 2.8. Optimistic Concurrency Control on Cycle-Scoped Writes

Two write operations are guarded by optimistic concurrency control against the adoption cycle's `version`: posting a contract award, and creating a purchase order. Both requests must carry `expected_cycle_version`, a non-optional input holding the cycle `version` the client last observed. Reading a cycle exposes its current `version` for exactly this purpose. If `expected_cycle_version` does not equal the cycle's current `version`, the request is rejected with `ERR_STALE_CYCLE_VERSION` (HTTP 412).

Both guarded writes are create-with-supersede operations: posting an award legitimately supersedes the previously selected quote, and creating a purchase order legitimately supersedes the cycle's existing draft purchase order. The guard exists so that a writer holding a stale cycle version cannot silently overwrite a newer award, nor supersede a draft purchase order it never observed. No other endpoint takes a version field; requests to any other operation must not include one.

### 2.9. Parallel Status Dimensions and Version Semantics

Two entities carry two independent status dimensions at once. An instructional material has an `adoption_status` (its journey through vetting, piloting, and board adoption) and an `availability_status` (its usability in the face of community challenges); the two move independently, so a material can legitimately be `ADOPTED` and `UNDER_CHALLENGE` at the same time. A purchase order has an `order_status` (its fulfillment journey) and a `payment_status` (its fiscal journey); a partially received order can simultaneously be partially paid.

Every state transition on every entity — whether driven by an explicit operator request or fired automatically by the system as a cascade — increments the affected entity's `version` by exactly one and refreshes its `updated_at`. When one operation mutates several entities (a board decision, a challenge removal cascade, a purchase receipt), each mutated entity is bumped independently. Operations that write fresh business data onto a resource without a status change likewise increment `version`: an award pinning a quote onto its cycle (§3.5), a purchase order creation marking its cycle (§3.6), an alignment re-post updating a mapping's rating (§3.2). Pure recomputes of system-computed values — `coverage_pct`, `provisional_composite`, `official_composite`, `participation_rate`, `best_value_score`, the ledger totals, the lot counters, `open_backorder_count`, and the live `submitted_review_count` — and the housekeeping writes that clear a cycle's quote pin on clarification (§3.5) or set `replacement_due` on removal (§3.9) refresh only `updated_at` and never increment `version`.

### 2.10. The Cycle Budget Ledger and Money Conservation

Every adoption cycle owns exactly one budget ledger, created automatically with the cycle and identified uniquely by its `cycle_id`. The ledger tracks `appropriation_total` (cumulative dollars appropriated to the cycle, growing from 0 via appropriation postings), `encumbered_total` (open commitments, starting at 0), and `expended_total` (cumulative payments, starting at 0). The `available_balance` is never stored; it is derived on every read as the appropriation total minus the encumbered total minus the expended total.

Money is conserved by invariant: at every instant, the appropriation total equals the sum of the available balance, the encumbered total, and the expended total. Six events move the ledger — an appropriation posting, a purchase order issue, a purchase order payment, a purchase order cancellation, a supplemental approval, and a supplemental revocation — and each is specified where its workflow lives in §3. An auditor can recompute `encumbered_total` independently and must reach the same figure: it equals the unpaid remainder (the `total_amount` minus the `amount_paid`) summed over the cycle's purchase orders whose `order_status` is `ISSUED`, `PARTIALLY_RECEIVED`, or `RECEIVED` and whose `payment_status` is `ENCUMBERED` or `PARTIALLY_PAID`, plus the `estimated_cost` summed over the cycle's supplemental requests in `APPROVED`, `UNDER_CHALLENGE`, or `REAFFIRMED` status. Reading the ledger returns an array of length 0 or 1.

### 2.11. Warehouse Lots and Unit Conservation

Each adopted material accumulates physical stock in a single inventory lot, unique per material and created automatically the first time a publisher receipt is posted for that material. The lot tracks `on_hand_units` (copies physically in the district warehouse), `in_transit_units` (copies shipped to schools but not yet received there), `delivered_units` (cumulative copies received by classrooms), and `total_received_units` (cumulative copies received from publishers); all four start at 0. Two further figures are derived rather than stored: `allocated_units`, the sum of `quantity` over the material's distribution orders in `APPROVED` status, and `available_units`, the `on_hand_units` minus the `allocated_units`.

Units are conserved by invariant: at every instant, `total_received_units` equals the sum of `on_hand_units`, `in_transit_units`, and `delivered_units`. Every movement — a publisher receipt, an approval allocation, a shipment, a school receipt, a cancellation release — changes the counters in exactly the way its workflow specifies in §3.7, and the invariant must hold before and after each one.

## 3. Business Logic & Workflows

### 3.1. Frameworks, Cycle Initiation, and Appropriations

Everything begins with the state framework. A `DistrictAdmin` registers a curriculum framework with a `code` (for example, "STATE-MATH-2026") — stored as supplied and never checked for uniqueness — a `subject_area` drawn from `MATHEMATICS`, `ENGLISH_LANGUAGE_ARTS`, `SCIENCE`, `SOCIAL_STUDIES`, or `WORLD_LANGUAGES`, a `grade_band` of `K_5`, `GRADES_6_8`, or `GRADES_9_12`, the `standards_required_count` — the total number of standards any candidate material will be mapped against, which must be at least 1 — and the `effective_year`, an integer naming the first school year the framework is in force. A framework is born `ACTIVE` unless its `status` is supplied otherwise, and only an `ACTIVE` framework may back a new cycle; a framework that has been `RETIRED` closes that door.

With a framework in place, a `CurriculumDirector` opens an adoption cycle by naming the `subject_area`, `grade_band`, the integer `school_year_start` in which the adopted materials will take effect, the backing `framework_id`, the `district_enrollment` for the grade band (an integer of zero or more students, feeding the replacement forecast of §3.10), and optionally the `award_method` — `LOWEST_RESPONSIVE` when omitted, or `BEST_VALUE` — which selects the winner rule used at award time. The referenced framework must exist, be `ACTIVE`, and match the cycle on both subject area and grade band; a missing, retired, or mismatched framework is rejected with `ERR_FRAMEWORK_MISMATCH`. A new cycle starts in `DRAFT` status, and its budget ledger is created alongside it with all totals at zero.

Money enters the cycle through appropriation postings: a `DistrictAdmin` posts an `amount`, which must be greater than zero, and that amount is added to the ledger's `appropriation_total`; the response (HTTP 200) carries the updated ledger. Appropriations are additive and may be posted repeatedly as the board funds the cycle.

An `InstructionalSpecialist` then moves the cycle from `DRAFT` to `ALIGNMENT_REVIEW`, opening the standards-mapping effort. Should the alignment work come back wanting, a `CurriculumDirector` may send the cycle from `ALIGNMENT_REVIEW` back to `DRAFT` — a deliberate revert loop that lets the office rework the slate before piloting. Any transition requested while the cycle is not in the required from-state is rejected with `ERR_INVALID_STATE`.

### 3.2. Material Submission and Standards Alignment

While a cycle is in `DRAFT` or `ALIGNMENT_REVIEW`, a `CurriculumDirector` submits candidate materials into it through the cycle's materials collection. Each submission carries a `title`, a `publisher_name`, an optional `isbn` (absent by default), and an optional `material_type` that defaults to `CORE` and may instead be `SUPPLEMENTAL`. A new material begins with `adoption_status` of `SUBMITTED`, `availability_status` of `USABLE`, and a `coverage_pct` of 0.00 — no standards mapped yet.

Vetting is the `InstructionalSpecialist`'s call. From `SUBMITTED`, a material may advance to `VETTED` — but only while its cycle is still in `DRAFT` or `ALIGNMENT_REVIEW`; vetting against a cycle that has moved on is rejected with `ERR_INVALID_STATE`, as is vetting a material that is not `SUBMITTED`. The specialist may instead reject a `SUBMITTED` material outright, moving it to `REJECTED`, which is terminal for the adoption dimension.

Alignment is recorded as mappings between the material and framework standards. An `InstructionalSpecialist` posts a `standard_code` together with a `coverage_rating` of `NONE`, `PARTIAL`, or `FULL`; neither the material's `adoption_status` nor the cycle's status gates the posting. The pair of material and `standard_code` acts as an upsert key: posting a code the material does not yet have creates the mapping (201), while posting an existing code updates that mapping's rating (200). Duplicate codes for one material are therefore impossible by construction. Every create or upsert recomputes the material's `coverage_pct`: each mapping contributes a weight — 1.0 for `FULL`, 0.5 for `PARTIAL`, 0.0 for `NONE` — and the percentage is one hundred times the sum of those weights divided by the backing framework's `standards_required_count`, rounded half-up to two decimal places. A material with no mappings reports 0.00.

The gate into piloting is the alignment gate: an `InstructionalSpecialist` moves the cycle from `ALIGNMENT_REVIEW` to `PILOT_OPEN`. Two checks guard it, evaluated in this order. First, at least one material of the cycle must be `VETTED`, or the attempt fails with `ERR_NO_VETTED_MATERIALS`. Second, every `VETTED` material of the cycle must show a `coverage_pct` of at least 85.00 — the boundary is inclusive, so exactly 85.00 passes — or the attempt fails with `ERR_ALIGNMENT_COVERAGE_BELOW_THRESHOLD`.

### 3.3. Pilot Programs and the Teacher Review Rubric

Once the cycle is `PILOT_OPEN`, a `CurriculumDirector` plans pilots. Planning a pilot names a `material_id` — the material must belong to the same cycle and be `VETTED`, or the request fails with `ERR_INVALID_STATE` — plus a `school_code`, an inclusive `starts_on` date, an exclusive `ends_on` date (which must fall after `starts_on`, or `ERR_VALIDATION`), and a `teacher_count` of at least 1, the number of piloting teachers who form the participation denominator. The district will not run overlapping pilots of the same subject at the same school: if the new pilot's window — occupying every date from `starts_on` up to but not including `ends_on` — overlaps the window of any `PLANNED` or `ACTIVE` pilot at the same `school_code` belonging to a cycle of the same `subject_area`, the request is rejected with `ERR_PILOT_WINDOW_CONFLICT`. A successfully planned pilot starts in `PLANNED` status.

Activation waits for the calendar and the cycle. A `CurriculumDirector` moves a pilot from `PLANNED` to `ACTIVE` only while the pilot's cycle is `PILOT_OPEN` (`ERR_INVALID_STATE` otherwise) and only once the logical clock's date has reached `starts_on`; an early activation is rejected with `ERR_PILOT_NOT_STARTED`. Activation has a side effect on the material: if the piloted material is still `VETTED`, it becomes a `PILOT_CANDIDATE` automatically. A pilot that will never run can be cancelled while `PLANNED`, moving to `CANCELLED`; a running pilot is closed by moving it from `ACTIVE` to `CLOSED`. Both `CLOSED` and `CANCELLED` are terminal.

Teachers score the pilots they teach. While a pilot is `ACTIVE`, a `Teacher` submits a rubric review with four integer dimension scores, each from 1 to 4: `pedagogy_score`, `alignment_score`, `usability_score`, and `equity_score`. A teacher may hold at most one `SUBMITTED` review per pilot; a second submission is rejected with `ERR_DUPLICATE_REVIEW`. Each review is recorded against its pilot as `pilot_id`, keeps the submitting teacher's identifier as `teacher_user_id`, stamps `submitted_at` from the logical clock, and computes its `review_composite` in exact decimal arithmetic as four-tenths of the pedagogy score, plus three-tenths of the alignment score, plus two-tenths of the usability score, plus one-tenth of the equity score. The pilot's `submitted_review_count` — a live count of its `SUBMITTED` reviews — and the material's `provisional_composite` are recomputed on every submission.

The provisional composite is the untrimmed mean of the `review_composite` values over all `SUBMITTED` reviews attached to pilots that reference this material within this cycle and are in `ACTIVE` or `CLOSED` status, rounded half-up to two decimal places; while no such reviews exist it is null. Reviews are only creatable while a pilot is `ACTIVE`, and withdrawn reviews are excluded from the pool, so pilots that are `PLANNED` or `CANCELLED` never contribute.

A teacher may withdraw a review while it is still `SUBMITTED` and while its pilot is still `ACTIVE` — withdrawing after the pilot has closed, or withdrawing a review that is not `SUBMITTED`, fails with `ERR_INVALID_STATE`, and withdrawing another teacher's review fails with `ERR_INSUFFICIENT_PERMISSIONS`. Withdrawal moves the review to `WITHDRAWN` and recomputes the pilot's `submitted_review_count` and the material's `provisional_composite` with the withdrawn review excluded.

When piloting is finished, a `CurriculumDirector` closes the pilots, moving the cycle from `PILOT_OPEN` to `SCORING`. The move requires that every pilot of the cycle has reached `CLOSED` or `CANCELLED`; a lingering `PLANNED` or `ACTIVE` pilot blocks it with `ERR_UNRESOLVED_PILOTS`. Close-pilots is the scoring event: for each material of the cycle that has at least one pilot, the system computes and persists two figures. The `official_composite` is the trimmed variant of the pilot composite — when the review pool (as defined for the provisional composite) holds at least five reviews, exactly one lowest and one highest `review_composite` are discarded, one instance each even when several reviews tie at an extreme, and the mean of the remaining values is rounded half-up to two decimal places; with fewer than five reviews, the official value is identical to the provisional one. The `participation_rate` is the count of `SUBMITTED` reviews across the material's pilots in this cycle that are `ACTIVE` or `CLOSED` at this moment, divided by the sum of those pilots' `teacher_count` values, rounded half-up to four decimal places; cancelled pilots contribute nothing, and when that denominator is zero the rate is null. Both figures stay null on a material until the cycle enters `SCORING`.

### 3.4. Public Review and the Board Decision

A `BoardSecretary` opens the public review, moving the cycle from `SCORING` to `PUBLIC_REVIEW`. Opening stamps the window onto the cycle: `public_review_opens_at` takes the current logical clock and `public_review_closes_at` is set thirty days later. The district keeps public reviews of the same subject from crowding one another: for every other cycle sharing this `subject_area` whose status is anything but `NOT_ADOPTED` and which already has a recorded review window, the new window must stand strictly clear by thirty days — either the new window opens more than thirty days after the existing window closes, or the existing window opens more than thirty days after the new window closes. Any other arrangement, including a gap of exactly thirty days, conflicts and is rejected with `ERR_PUBLIC_REVIEW_WINDOW_CONFLICT`.

When the window has run its course, the `BoardSecretary` closes the review, moving the cycle from `PUBLIC_REVIEW` to `BOARD_PENDING`. Closing requires the logical clock to have reached `public_review_closes_at`; the boundary is inclusive, so closing at exactly the close instant passes, while an earlier attempt fails with `ERR_PUBLIC_REVIEW_NOT_CLOSED`. Should the board find the slate wanting more comment, the `BoardSecretary` may remand the cycle from `BOARD_PENDING` back to `PUBLIC_REVIEW`; the window re-opens, with `public_review_opens_at` re-stamped to the current clock and `public_review_closes_at` set thirty days after it; the thirty-day clear-gap check is evaluated only on the initial opening from `SCORING`, never on a remand.

The board decision itself is recorded by the `BoardSecretary` with a `material_id` and a `decision` of `ADOPT` or `REJECT`, and only while the cycle is `BOARD_PENDING`. An adoption decision names a material of this cycle whose `adoption_status` is `PILOT_CANDIDATE` — anything else fails with `ERR_INVALID_STATE` — and then applies two quality gates in a fixed order. The composite gate runs first: the material's `official_composite` must be at least 3.20, with exactly 3.20 passing and a null composite failing outright, or the decision is rejected with `ERR_COMPOSITE_BELOW_THRESHOLD`. The participation gate runs only after the composite gate has passed: the material's `participation_rate` must be at least 0.60, with exactly 0.60 passing and a null rate failing outright, or the decision is rejected with `ERR_PARTICIPATION_BELOW_FLOOR`. A successful adoption moves the chosen material to `ADOPTED`, stamps its `adopted_at` from the logical clock, records it on the cycle as `adopted_material_id`, moves every other `PILOT_CANDIDATE` material of the cycle to `REJECTED`, and advances the cycle to `ADOPTED`.

A rejection decision is the slate-killer: the named material must exist but is otherwise unexamined, every `PILOT_CANDIDATE` material of the cycle moves to `REJECTED`, and the cycle moves to `NOT_ADOPTED`, a terminal status. Either decision's response (HTTP 200) carries the updated cycle. The cycle's other terminal status, `SUNSET`, arrives only at the end of a successful lifecycle (§3.7).

### 3.5. Publisher Quotes, Evaluation, and Contract Award

Publishers bid through quotes managed by a `ProcurementOfficer`. A quote may be submitted into a cycle whose status is `PILOT_OPEN`, `SCORING`, `PUBLIC_REVIEW`, `BOARD_PENDING`, `ADOPTED`, or `PROCURING`, naming a `material_id` of that cycle whose `adoption_status` is `VETTED`, `PILOT_CANDIDATE`, or `ADOPTED`, together with a `publisher_name`. The commercial terms are the `print_unit_price` and `print_quantity` (unit price and copy count, each zero or more), the `digital_seat_rate` and `digital_seat_count` (per-student license price and seat count, each zero or more), an optional `bundle_discount_pct` between 0 and 1 that defaults to 0, and the service terms `training_sessions` and `license_years`, each zero or more. A new quote starts `SUBMITTED`, stamped with `submitted_at` from the logical clock.

Evaluation begins when the `ProcurementOfficer` moves a `SUBMITTED` quote to `UNDER_EVALUATION`, which computes its `evaluated_total`. The evaluated total follows the bundled pricing rule, and its rounding order is pinned: first the print line is computed as `print_unit_price` times `print_quantity` and rounded half-up to cents; likewise the digital line is computed as `digital_seat_rate` times `digital_seat_count` and rounded half-up to cents. Second, when a positive `bundle_discount_pct` is present and both the print and digital quantities are greater than zero, the bundle discount applies to the digital line only — the already-rounded digital line is multiplied by one minus the discount and the result is rounded half-up to cents again. Last, the total is the sum of the two rounded lines. Summing the unrounded lines and rounding once at the end yields different cents and is not the specification.

A quote under evaluation may be sent for clarification, moving from `UNDER_EVALUATION` to `CLARIFICATION_REQUESTED`, and the publisher's revision returns it from `CLARIFICATION_REQUESTED` to `UNDER_EVALUATION`; the resubmission may carry updated values for any of the pricing or service fields (`print_unit_price`, `print_quantity`, `digital_seat_rate`, `digital_seat_count`, `bundle_discount_pct`, `training_sessions`, `license_years`), a field omitted or supplied as `null` keeps its current value, and the `evaluated_total` is recomputed on each resubmit. The loop may iterate, and each pass bumps the quote's `version` — which is exactly what makes the cycle's quote pin meaningful. A quote may also be withdrawn from `SUBMITTED`, `UNDER_EVALUATION`, or `CLARIFICATION_REQUESTED`, moving to `WITHDRAWN`, terminal alongside `REJECTED` and `SUPERSEDED`.

The award is the procurement climax: a `ProcurementOfficer` posts an award naming a `quote_id` while the cycle is `ADOPTED` (a first award) or `PROCURING` (a re-award). The request is OCC-guarded with `expected_cycle_version` per §2.8, so a stale cycle version is rejected with `ERR_STALE_CYCLE_VERSION` (HTTP 412) before any business rule runs. After the state and version checks, three business checks run in a fixed order. First, the named quote's `material_id` must equal the cycle's `adopted_material_id`, or the award fails with `ERR_QUOTE_MATERIAL_MISMATCH`. Second, the responsive pool — all quotes of this cycle in `UNDER_EVALUATION` whose material is the adopted material, the award target included — must satisfy the bid rule: at least three responsive quotes when the target's `evaluated_total` is at least 250,000.00 dollars (a target priced at exactly 250,000.00 is held to this formal-bid rule), and at least two otherwise; a short pool fails with `ERR_BID_RULE_NOT_SATISFIED`. Third, the target must be the rule winner, or the award fails with `ERR_QUOTE_NOT_AWARD_WINNER`. Under `LOWEST_RESPONSIVE`, the winner is the pool quote with the lowest `evaluated_total`, ties broken in favor of the earliest `created_at`. Under `BEST_VALUE`, the system first computes and persists a `best_value_score` for every quote in the pool — the price score is one hundred when the pool's minimum `evaluated_total` is zero, and otherwise the larger of zero and one hundred times two-minus-the-ratio of the quote's `evaluated_total` to that minimum; the training score is ten points per included `training_sessions`, capped at one hundred; the license score is twenty points per `license_years`, capped at one hundred; the final score is half the price score plus a quarter of the training score plus a quarter of the license score, combined at full precision and rounded half-up to two decimal places only at the end — and the winner is the highest score, ties again broken by the earliest `created_at`. A quote's `best_value_score` remains null unless its cycle awards under `BEST_VALUE`.

A successful award moves the target quote from `UNDER_EVALUATION` to `SELECTED` and pins it onto the cycle: `pinned_quote_id` records the quote and `quote_version_pin` captures the quote's `version` at that instant. Every other responsive quote of the pool moves to `REJECTED`. On a re-award while `PROCURING`, the previously `SELECTED` quote moves to `SUPERSEDED` — a legitimate, intended write, which is precisely what the OCC rule guards — and the pin moves to the new winner. The first award advances the cycle from `ADOPTED` to `PROCURING`; a re-award leaves it in `PROCURING`. The award response (HTTP 200) carries the updated cycle.

One escape hatch matters later: sending a `SELECTED` quote to `CLARIFICATION_REQUESTED` clears the cycle's pin — both `pinned_quote_id` and `quote_version_pin` return to null — because the quote under clarification is no longer the version the district agreed to buy. A fresh award is required before any purchase order can be created.

### 3.6. Purchase Orders, Receipts, and Payments

With a quote pinned, a `ProcurementOfficer` creates a purchase order against the cycle, supplying the `quote_id`, a `print_quantity` of at least 1, a `digital_seat_count` of zero or more, and — because this is the second create-with-supersede write of §2.8 — an `expected_cycle_version` matching the cycle's current `version`, with a mismatch rejected as `ERR_STALE_CYCLE_VERSION` (HTTP 412). The named quote must be the cycle's currently pinned selection: its status must be `SELECTED`, it must be the quote recorded in `pinned_quote_id`, and its current `version` must equal the cycle's `quote_version_pin`; a quote that was never selected, was superseded, or had its pin cleared by a clarification fails with `ERR_QUOTE_NOT_SELECTED`. The order's `total_amount` is computed by the same bundled pricing rule as quote evaluation — the pinned rounding order of §3.5 — but priced off the pinned quote's rates against the purchase order's own quantities. The cycle ledger must cover the order before it exists: an `available_balance` smaller than the `total_amount` fails with `ERR_BUDGET_ENVELOPE_EXCEEDED` (HTTP 402), while a balance exactly equal to the total passes.

Creation records the quote's version onto the order as its own `quote_version_pin`, starts the order at `order_status` `DRAFT` and `payment_status` `UNENCUMBERED` with `amount_paid` and `received_print_qty` at zero, supersedes any existing `DRAFT` purchase order of the same cycle (that draft moves to `SUPERSEDED`), and bumps the cycle's `version`.

Issuing is the fiscal commitment: a `ProcurementOfficer` issues a `DRAFT` order, moving it to `ISSUED` and its payment dimension from `UNENCUMBERED` to `ENCUMBERED`, adding the full `total_amount` to the ledger's `encumbered_total`. Issuance re-checks the envelope — the ledger's `available_balance` must be at least the `total_amount`, with an exactly equal balance passing and a shortfall rejected as `ERR_BUDGET_ENVELOPE_EXCEEDED`.

Receipts are posted by a `WarehouseManager` as `qty_received`, which must be at least 1 (`ERR_VALIDATION` otherwise), against an order that is `ISSUED` or `PARTIALLY_RECEIVED` (`ERR_INVALID_STATE` otherwise). A receipt may never push the cumulative `received_print_qty` beyond the ordered `print_quantity`; an over-receipt is rejected with `ERR_OVER_RECEIPT`. A successful receipt adds `qty_received` to `received_print_qty` and advances the order to `PARTIALLY_RECEIVED` while copies remain outstanding, or to `RECEIVED` when the cumulative count reaches `print_quantity`. The same receipt feeds the warehouse: the material's inventory lot — auto-created on this first receipt if none exists — gains `qty_received` in both `on_hand_units` and `total_received_units`. The receipt then runs the backorder promotion pass and recomputes the cycle's backorder count (§3.7). Finally, the very first receipt posted for the cycle advances the cycle itself from `PROCURING` to `DISTRIBUTING` automatically.

Payments move money from encumbered to expended. A `ProcurementOfficer` pays an `amount`, which must be greater than zero, against an order whose `order_status` is `ISSUED`, `PARTIALLY_RECEIVED`, or `RECEIVED` and whose `payment_status` is `ENCUMBERED` or `PARTIALLY_PAID`; any other combination fails with `ERR_INVALID_STATE`. The amount may not exceed the outstanding balance — `total_amount` minus `amount_paid` — or the payment fails with `ERR_PAYMENT_EXCEEDS_BALANCE`; paying exactly the outstanding balance is permitted. A payment adds the amount to `amount_paid`, moves the payment dimension to `PARTIALLY_PAID` while a balance remains or to `PAID` when the order is fully paid, subtracts the amount from the ledger's `encumbered_total`, and adds it to `expended_total`.

Closing and cancelling wind an order down. A fully received order moves from `RECEIVED` to `CLOSED`, but only once its `payment_status` is `PAID`; closing earlier fails with `ERR_PO_NOT_CLOSABLE`. Cancellation is available from `DRAFT`, `ISSUED`, or `PARTIALLY_RECEIVED` and moves the order to `CANCELLED` with its payment dimension set to `RELEASED`; when the order carried an encumbrance (its payment status was `ENCUMBERED` or `PARTIALLY_PAID`), the unpaid remainder — `total_amount` minus `amount_paid` — is released from the ledger's `encumbered_total`, while `expended_total` is left unchanged: money already paid stays expended. `CLOSED`, `CANCELLED`, and `SUPERSEDED` are the order's terminal states.

### 3.7. Warehouse Inventory and Classroom Distribution

The inventory lot narrated in §2.11 lives entirely off the events of this workflow: receipts add to `on_hand_units` and `total_received_units`; approvals add to the derived `allocated_units`; shipments subtract the shipped `quantity` from `on_hand_units` and `allocated_units` while adding it to `in_transit_units` (leaving `available_units` unchanged, since the stock was already spoken for); school receipts subtract the quantity from `in_transit_units` and add it to `delivered_units`; and a cancelled approval releases its `allocated_units`.

Classroom demand arrives as distribution orders created by a `WarehouseManager`, each naming a `material_id`, a destination `school_code` and `classroom_label`, a `quantity` of at least 1, and a `need_priority` from 1 to 5 with 5 the most urgent. Distribution exists only for adopted, unfrozen materials: a material whose `adoption_status` is not `ADOPTED` fails with `ERR_MATERIAL_NOT_ADOPTED`, and a material whose `availability_status` is anything but `USABLE` fails with `ERR_MATERIAL_FROZEN`. A new order starts `REQUESTED`.

Approval commits stock. A `WarehouseManager` approves an order from `REQUESTED` or `BACKORDERED`; the freeze check runs before the inventory check, so a non-`USABLE` material fails with `ERR_MATERIAL_FROZEN` even when stock would have sufficed, and only then must the lot's `available_units` cover the requested `quantity` — an exactly equal availability passes, leaving `available_units` at zero, while a shortfall fails with `ERR_INSUFFICIENT_INVENTORY`. Approval adds the `quantity` to the lot's `allocated_units` and recomputes the cycle's `open_backorder_count`. When stock is short, the manager may instead move a `REQUESTED` order to `BACKORDERED`, which likewise recomputes the count. The cycle's `open_backorder_count` is the number of its adopted material's distribution orders sitting in `BACKORDERED`, recomputed on every allocation event — every approval, backordering, promotion, cancellation, or receipt.

Publisher receipts are the backorder lifeline. Each receipt runs a promotion pass over the received material's `BACKORDERED` orders, ranked by `need_priority` descending with ties broken by `created_at` ascending. The head of that ranking is promoted to `APPROVED` — committing its `quantity` into `allocated_units` — for as long as the head fits within `available_units`; the pass stops at the first order that does not fit, and later orders are not considered, a strict head-of-line blocking discipline.

Fulfillment continues with shipment: an `APPROVED` order moves to `SHIPPED`, and the school confirms arrival by moving a `SHIPPED` order to `RECEIVED`. Cancellation is available from `REQUESTED`, `APPROVED`, or `BACKORDERED` and moves the order to `CANCELLED`; when the cancelled order had been `APPROVED`, its `quantity` is released from `allocated_units`, and the cycle's `open_backorder_count` is recomputed. `RECEIVED` and `CANCELLED` are terminal.

The cycle itself completes downstream of this work. Once distribution has run, a `CurriculumDirector` moves the cycle from `DISTRIBUTING` to `ACTIVE` — but only when no open work remains: every purchase order of the cycle must be in `CLOSED`, `CANCELLED`, or `SUPERSEDED`, and every distribution order for the adopted material must be `RECEIVED` or `CANCELLED`, or the transition fails with `ERR_OPEN_WORK_REMAINS`. An `ACTIVE` cycle is the steady state of a live adoption, and when the materials reach the end of their classroom life a `CurriculumDirector` sunsets the cycle from `ACTIVE` to `SUNSET`, terminal.

### 3.8. Supplemental Material Requests and Vetting

Outside the core adoption, a `Teacher` may request a supplemental purchase by naming the `cycle_id` it should draw against, a `title`, a `publisher_name`, an `estimated_cost` greater than zero, the `subject_area` and `grade_band` it supports, the requesting `school_code`, and an optional `justification`. The request records its filer as `requester_user_id` and starts in `SUBMITTED` status.

An `InstructionalSpecialist` picks up the vetting queue, moving a request from `SUBMITTED` to `VETTING`. From `VETTING` the specialist may deny the request, moving it to `DENIED`, terminal — or approve it, which is where the safeguards bite. Segregation of duties forbids self-approval: the approver's identity must differ from the recorded `requester_user_id`, or the approval fails with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). The fiscal envelope also applies: the cycle ledger's `available_balance` must be at least the `estimated_cost`, with an exactly equal balance passing and a shortfall rejected as `ERR_BUDGET_ENVELOPE_EXCEEDED`. A successful approval stamps the request with the approver's identity as `approver_user_id` and the logical clock as `approved_at`, and commits the `estimated_cost` into the ledger's `encumbered_total`.

Challenges interact with supplemental requests on their own cycle of statuses. Filing a challenge against an `APPROVED` or `REAFFIRMED` request moves it to `UNDER_CHALLENGE`; the encumbrance is deliberately not released while the challenge pends. A challenge decided in the district's favor returns the request from `UNDER_CHALLENGE` to `REAFFIRMED` — and a reaffirmed request may be challenged again, so the loop between `APPROVED` or `REAFFIRMED` and `UNDER_CHALLENGE` is cyclic. A challenge decided against the request moves it from `UNDER_CHALLENGE` to `REVOKED`, terminal, releasing the `estimated_cost` from the ledger's `encumbered_total`.

### 3.9. Challenges, Committee Votes, and Appeals

The reconsideration process gives the community a formal voice. A `CommunityMember` files a challenge naming a `target_type` of `MATERIAL` or `SUPPLEMENTAL_REQUEST`, a `target_id` interpreted according to that type — a material identifier when the type is `MATERIAL`, a supplemental request identifier when it is `SUPPLEMENTAL_REQUEST` — and `grounds` of `CONTENT_OBJECTION`, `AGE_APPROPRIATENESS`, `ALIGNMENT_DISPUTE`, or `PROCEDURAL_IRREGULARITY`. The target must exist (`ERR_NOT_FOUND` names the missing resource type) and must be eligible: a material is challengeable only when its `adoption_status` is `ADOPTED`, and a supplemental request only in `APPROVED` or `REAFFIRMED`; anything else fails with `ERR_CHALLENGE_TARGET_INVALID`. Timeliness is enforced against the logical clock: a challenge must be filed no later than ninety days after the target's `adopted_at` or `approved_at` instant, and a filing more than ninety days after it is rejected with `ERR_CHALLENGE_WINDOW_CLOSED`. Finally, one open challenge per target: if the target already has a challenge in any non-terminal status — `FILED` through `APPEALED` — the new filing fails with `ERR_OPEN_CHALLENGE_EXISTS`. Per the §2.7 cascade these checks evaluate window-first (a target carrying no adoption or approval stamp has no window to violate), then the one-open-challenge rule, then target eligibility.

Filing stamps the case with the filer's identity as `filer_user_id`, the logical clock as `filed_at`, a `vote_round` of 1, and `appeal_used` of false, and opens in `FILED` status. Filing also freezes the target: a `USABLE` material moves to `UNDER_CHALLENGE` — its `adoption_status` untouched, per §2.9 — and an `APPROVED` or `REAFFIRMED` supplemental request moves to `UNDER_CHALLENGE` with its encumbrance intact.

Administration of the case belongs to the `CurriculumDirector`: from `FILED` to `SCREENING`, then into `COMMITTEE_REVIEW`, and optionally on to `HEARING`. After an appeal, the case returns to `COMMITTEE_REVIEW` directly from `APPEALED`.

A `CommitteeMember` casts a `vote` of `UPHOLD`, `RESTRICT`, or `REMOVE` against a case in any status — the ballot box is gated only by the two integrity rules below, never by the case's status; the ballot records the case as `challenge_id`, the voter's identity as `voter_user_id`, and pins the case's current `vote_round` at cast time, immutable thereafter — and, per §2.5, the vote record itself carries no `updated_at` or `version`. Two integrity rules guard the ballot box: the case's filer may not vote on their own case (`ERR_SEGREGATION_OF_DUTIES`, HTTP 403), and each member casts at most one vote per round — a second vote in the same `vote_round` fails with `ERR_DUPLICATE_VOTE`.

Decision day requires quorum. A `CommitteeMember` issues the decision from `COMMITTEE_REVIEW` or `HEARING`, and at least three votes must exist in the current `vote_round` — exactly three passes, fewer fails with `ERR_QUORUM_NOT_MET`. The recorded `decision` is the plurality of the current round's ballots: `UPHOLD` ballots produce `UPHELD`, `RESTRICT` ballots produce `RESTRICTED`, `REMOVE` ballots produce `REMOVED`, and any tie for the top count resolves to `UPHELD`. The decision stamps `decided_at` from the logical clock and fires the target cascade. For a material target: `UPHELD` returns availability to `USABLE` from `UNDER_CHALLENGE` and `RESTRICTED` alike; `RESTRICTED` moves it to `RESTRICTED`; `REMOVED` moves it to `REMOVED` — reachable from `UNDER_CHALLENGE` and from `RESTRICTED` alike, since a restricted-but-still-adopted material remains challengeable — and removal carries the full cascade: every distribution order for the material in `REQUESTED`, `APPROVED`, or `BACKORDERED` is cancelled, approved orders release their allocations from the lot, the lot's derived figures are recomputed, and when the removed material is its cycle's `adopted_material_id`, that cycle's `replacement_due` flag is set to true. For a supplemental target: `UPHELD` reaffirms the request, while `RESTRICTED` or `REMOVED` revokes it with the encumbrance release of §3.8.

The filer gets one appeal. From `DECIDED`, the original filer — and only the filer, or `ERR_INSUFFICIENT_PERMISSIONS` — may appeal the case to `APPEALED`, provided `appeal_used` is still false (a second appeal fails with `ERR_INVALID_STATE`) and the logical clock is no later than fourteen days after `decided_at`, with an appeal at exactly the fourteen-day mark admitted and a later one rejected as `ERR_APPEAL_WINDOW_CLOSED`. Appealing sets `appeal_used` to true and increments `vote_round`, so the returning committee votes in a fresh round under the same one-vote-per-member-per-round rule; the case flows `APPEALED` back into `COMMITTEE_REVIEW` and onward to a second decision, which is final because `appeal_used` blocks any further appeal.

Closure belongs to the `CurriculumDirector`: a `DECIDED` case moves to `CLOSED`, terminal, once either the appeal has been used or the appeal window has lapsed — that is, the logical clock has passed fourteen days after `decided_at`. Closing while an appeal is still available fails with `ERR_INVALID_STATE`.

### 3.10. Replacement Planning and the Budget Forecast

A cycle whose adopted material was removed by challenge carries `replacement_due` set to true; the flag gates nothing by itself, but it feeds the district's forward planning, which is served as a computed read: requesting the cycle's budget forecast with a `variant` of `ROLLING` or `STRAIGHT_LINE` — a missing or unrecognized `variant` is rejected with `ERR_VALIDATION` (HTTP 400) — returns an object naming the `variant`, the `base_amount`, the `contingency_rate`, and the resulting `forecast_total`.

The evaluation order is pinned, because the base feeds the tier selection: first the base amount is computed and rounded half-up to two decimal places; second the contingency rate is selected from the tier table keyed on that rounded base; third the forecast total is the base multiplied by one plus the contingency rate, rounded half-up to two decimal places.

Under `ROLLING`, the model is forward-looking and ignores historical spend: the base is the cycle's `district_enrollment` multiplied by a per-pupil rate of 120.00 dollars, by a replacement ratio of 0.20, and by a five-year horizon, rounded half-up to two decimal places. Under `STRAIGHT_LINE`, the model is chronological: it gathers the `expended_total` of the three most recent other cycles in `ACTIVE` or `SUNSET` status — the queried cycle is excluded even when it qualifies — ordered by `school_year_start` descending with ties broken by `created_at` ascending, never by `id`; when that history is empty the base is 0.00, and otherwise the base is the mean of those expenditures multiplied by 1.03 raised to the fifth power — three percent inflation compounded over the same five-year horizon — rounded half-up to two decimal places. The two variants therefore answer different questions and, given identical cycle state, generally return different forecasts.

The contingency tiers key on the rounded base: a base below 100,000.00 dollars carries a rate of 0.05; a base of at least 100,000.00 and below 500,000.00 carries 0.08; a base of at least 500,000.00 carries 0.12.

## 4. Endpoint Definitions

Operations that create a new resource — including members added to a nested collection, such as a material under a cycle — return `201 Created`; operations that modify an existing resource return `200 OK`. The one blended case is the alignment mapping upsert: it returns `201 Created` when the mapping is created and `200 OK` when an existing mapping is updated. List endpoints accept `limit` and `offset`; many also accept filters — frameworks by `subject_area` and `status`; cycles by `framework_id`, `subject_area`, and `status`; materials by `cycle_id`, `adoption_status`, and `availability_status`; pilots by `cycle_id`, `material_id`, `school_code`, and `status`; reviews by `status`; quotes by `cycle_id`, `material_id`, and `status`; purchase orders by `cycle_id`, `quote_id`, `order_status`, and `payment_status`; a material's distribution orders and the flat distribution list by `status`, and the flat list additionally by `material_id` and `school_code`; supplemental requests by `cycle_id` and `status`; challenges by `target_id` and `status`; and votes by `vote_round`. Filters match by exact equality, and a filter value that matches nothing simply yields an empty page; the one exception is the votes `vote_round` filter, which must parse as an integer and otherwise fails with `ERR_VALIDATION` (HTTP 400). In the table below, "Any" means any of the nine roles. Request and response bodies are specified by the workflows of §3, not here.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server's logical clock | DistrictAdmin |
| POST | `/frameworks` | Create a state curriculum framework | DistrictAdmin |
| GET | `/frameworks` | List frameworks | Any |
| GET | `/frameworks/{frameworkId}` | Get one framework | Any |
| POST | `/adoption-cycles` | Create an adoption cycle and its budget ledger | CurriculumDirector |
| GET | `/adoption-cycles` | List adoption cycles | Any |
| GET | `/adoption-cycles/{cycleId}` | Get one adoption cycle (includes `version` for OCC clients) | Any |
| POST | `/adoption-cycles/{cycleId}/transitions` | Drive the cycle state machine via `to_state` | CurriculumDirector, InstructionalSpecialist, BoardSecretary |
| POST | `/adoption-cycles/{cycleId}/board-decision` | Record the board's adoption or rejection decision | BoardSecretary |
| POST | `/adoption-cycles/{cycleId}/award` | Award the contract to a quote (OCC-guarded) | ProcurementOfficer |
| POST | `/adoption-cycles/{cycleId}/budget-appropriation` | Post an additive appropriation to the cycle ledger | DistrictAdmin |
| GET | `/adoption-cycles/{id}/budget-ledger` | Read the cycle's budget ledger (array of length 0 or 1) | Any |
| GET | `/adoption-cycles/{cycleId}/budget-forecast` | Compute the replacement budget forecast for a `variant` | Any |
| POST | `/adoption-cycles/{cycleId}/materials` | Submit a material into the cycle | CurriculumDirector |
| GET | `/materials` | List materials | Any |
| GET | `/materials/{materialId}` | Get one material | Any |
| POST | `/materials/{materialId}/transitions` | Drive the material adoption dimension via `to_state` | InstructionalSpecialist |
| POST | `/materials/{id}/alignments` | Create or upsert an alignment mapping | InstructionalSpecialist |
| GET | `/materials/{id}/alignments` | List a material's alignment mappings | Any |
| POST | `/adoption-cycles/{cycleId}/pilots` | Plan a pilot of a vetted material at a school | CurriculumDirector |
| GET | `/pilots` | List pilots | Any |
| GET | `/pilots/{pilotId}` | Get one pilot | Any |
| POST | `/pilots/{pilotId}/transitions` | Drive the pilot machine via `to_state` | CurriculumDirector |
| POST | `/pilots/{id}/reviews` | Submit a teacher rubric review for an active pilot | Teacher |
| GET | `/pilots/{id}/reviews` | List a pilot's reviews | Any |
| POST | `/reviews/{reviewId}/withdraw` | Withdraw the caller's own submitted review | Teacher |
| POST | `/adoption-cycles/{cycleId}/quotes` | Submit a publisher quote for a material of the cycle | ProcurementOfficer |
| GET | `/quotes` | List quotes | Any |
| GET | `/quotes/{quoteId}` | Get one quote | Any |
| POST | `/quotes/{quoteId}/transitions` | Drive the quote machine via `to_state`, including resubmission | ProcurementOfficer |
| POST | `/adoption-cycles/{cycleId}/purchase-orders` | Create a draft purchase order against the pinned quote (OCC-guarded) | ProcurementOfficer |
| GET | `/purchase-orders` | List purchase orders | Any |
| GET | `/purchase-orders/{poId}` | Get one purchase order | Any |
| POST | `/purchase-orders/{poId}/issue` | Issue a draft purchase order, encumbering its total | ProcurementOfficer |
| POST | `/purchase-orders/{poId}/receive` | Post a publisher receipt and run backorder promotion | WarehouseManager |
| POST | `/purchase-orders/{poId}/pay` | Pay against an issued purchase order | ProcurementOfficer |
| POST | `/purchase-orders/{poId}/cancel` | Cancel a non-terminal purchase order, releasing its unpaid encumbrance | ProcurementOfficer |
| POST | `/purchase-orders/{poId}/transitions` | Close a fully received, fully paid purchase order via `to_state` | ProcurementOfficer |
| GET | `/materials/{id}/inventory-lots` | Read the material's inventory lot (array of length 0 or 1) | Any |
| GET | `/materials/{id}/distribution-orders` | List distribution orders targeting a material | Any |
| POST | `/distribution-orders` | Request classroom distribution of an adopted, usable material | WarehouseManager |
| GET | `/distribution-orders` | List distribution orders | Any |
| POST | `/distribution-orders/{doId}/transitions` | Drive the distribution machine via `to_state` | WarehouseManager |
| POST | `/supplemental-requests` | File a supplemental material request | Teacher |
| GET | `/supplemental-requests` | List supplemental requests | Any |
| GET | `/supplemental-requests/{srId}` | Get one supplemental request | Any |
| POST | `/supplemental-requests/{srId}/transitions` | Drive the vetting machine via `to_state` | InstructionalSpecialist |
| POST | `/challenge-cases` | File a challenge against an eligible target | CommunityMember |
| GET | `/challenge-cases` | List challenge cases | Any |
| GET | `/challenge-cases/{ccId}` | Get one challenge case | Any |
| POST | `/challenge-cases/{ccId}/transitions` | Drive the challenge machine via `to_state` | CurriculumDirector, CommitteeMember, CommunityMember |
| POST | `/challenge-cases/{id}/votes` | Cast an immutable committee vote for the current round | CommitteeMember |
| GET | `/challenge-cases/{id}/votes` | List a challenge's votes across all rounds | Any |

## 5. Error Code Catalogue

Trigger conditions for each error live in the workflow narratives of §2 and §3; this table is the identifier reference.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_VALIDATION` | 400 Bad Request |
| `ERR_INVALID_PAGINATION_PARAMETERS` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_UNRESOLVED_PILOTS` | 409 Conflict |
| `ERR_OPEN_WORK_REMAINS` | 409 Conflict |
| `ERR_PILOT_NOT_STARTED` | 409 Conflict |
| `ERR_PUBLIC_REVIEW_NOT_CLOSED` | 409 Conflict |
| `ERR_CHALLENGE_WINDOW_CLOSED` | 409 Conflict |
| `ERR_APPEAL_WINDOW_CLOSED` | 409 Conflict |
| `ERR_PILOT_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_PUBLIC_REVIEW_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_MATERIAL_FROZEN` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_ALIGNMENT_COVERAGE_BELOW_THRESHOLD` | 409 Conflict |
| `ERR_NO_VETTED_MATERIALS` | 409 Conflict |
| `ERR_COMPOSITE_BELOW_THRESHOLD` | 409 Conflict |
| `ERR_PARTICIPATION_BELOW_FLOOR` | 409 Conflict |
| `ERR_BID_RULE_NOT_SATISFIED` | 409 Conflict |
| `ERR_QUOTE_NOT_AWARD_WINNER` | 409 Conflict |
| `ERR_QUOTE_NOT_SELECTED` | 409 Conflict |
| `ERR_QUOTE_MATERIAL_MISMATCH` | 409 Conflict |
| `ERR_INSUFFICIENT_INVENTORY` | 409 Conflict |
| `ERR_OVER_RECEIPT` | 409 Conflict |
| `ERR_PO_NOT_CLOSABLE` | 409 Conflict |
| `ERR_PAYMENT_EXCEEDS_BALANCE` | 409 Conflict |
| `ERR_QUORUM_NOT_MET` | 409 Conflict |
| `ERR_DUPLICATE_VOTE` | 409 Conflict |
| `ERR_DUPLICATE_REVIEW` | 409 Conflict |
| `ERR_OPEN_CHALLENGE_EXISTS` | 409 Conflict |
| `ERR_FRAMEWORK_MISMATCH` | 409 Conflict |
| `ERR_MATERIAL_NOT_ADOPTED` | 409 Conflict |
| `ERR_CHALLENGE_TARGET_INVALID` | 409 Conflict |
| `ERR_BUDGET_ENVELOPE_EXCEEDED` | 402 Payment Required |
| `ERR_STALE_CYCLE_VERSION` | 412 Precondition Failed |
