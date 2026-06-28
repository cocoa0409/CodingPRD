# Collectibles Grading & Authentication API — Product Requirements Document

## 1. Introduction

Professional grading houses for trading cards, comics, and similar collectibles operate a tightly choreographed pipeline: a customer ships a batch of items, chooses a turnaround tier, and pays a fee that depends both on the service level and on the declared value of each item. The lab receives each piece, verifies it against the declaration, grades it across four physical dimensions, authenticates it, and finally seals it inside a tamper-evident holder — a **slab** — bearing a unique certificate number and a printed grade label. Every encapsulation also moves a population census that records how many copies of a given collectible exist at a given grade.

This document specifies the API that orchestrates that workflow end-to-end. The system must reconcile two recurring tensions. First, money is quoted twice — an **estimate** is pinned when the customer submits, and a **final fee** is computed when each item is sealed — and the two deliberately diverge when an item's declared value exceeds its tier cap or when the item was cracked and regraded. Second, a sealed item is not necessarily final: a customer who believes an item was undergraded may request a **crack-and-regrade**, which physically destroys the existing slab, returns the item to the grading queue, and decrements the population census, then re-runs the whole grading-to-encapsulation loop. Because two regrade requests can target the same item, the system applies optimistic concurrency control so that a stale request cannot silently overwrite a slab it never observed.

The remainder of this document defines the global request/response contract, the role model, the cross-cutting fiscal and consistency principles, and the detailed business workflows that govern each entity's lifecycle.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request other than customer registration and the test-clock control endpoint must be authenticated through two mandatory HTTP headers. `X-User-ID` identifies the acting user, and `X-User-Role` declares the operational capacity in which the call is made. If either header is missing or malformed, the request is rejected with `ERR_UNAUTHENTICATED`. When the headers are present but the named role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`.

The system recognizes six roles, spelled exactly as follows: `Anonymous`, `Customer`, `Receiver`, `Grader`, `Authenticator`, and `LabAdmin`.

The meaning of `X-User-ID` depends on the role. When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer`; ownership checks on any resource that references a `Customer` compare the resource's customer foreign key to `X-User-ID`. Concretely, a `Customer` may submit, add items to, delete items from, or open a regrade request against a `Submission` only when the `customer_id` recorded on that `Submission` equals `X-User-ID`; otherwise the request is rejected with `ERR_NOT_OWNER`.

The remaining roles carry an opaque identifier. When `X-User-Role` is `Anonymous`, `X-User-ID` is an opaque caller identifier not tied to any persisted entity; the `Anonymous` role exists only to register a customer and to set the test clock. When `X-User-Role` is `Receiver`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server records it as `received_by_user_id` on the `IntakeRecord` that the receiver logs, but it does not compare it to any entity's `id`. When `X-User-Role` is `Authenticator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server records it as `authenticator_user_id` on the `AuthenticationCheck` it produces, but does not compare it to any entity's `id`. When `X-User-Role` is `Grader`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity, and the server does not compare it to any entity's `id`. When `X-User-Role` is `LabAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity used for configuration, shipping, and administrative actions, and the server does not compare it to any entity's `id`.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0. A `limit` or `offset` outside these bounds is rejected with `ERR_PAGINATION_INVALID`.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order.

Paginated and non-paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Most resources in the system carry a standard set of system-managed fields:

- **`id`** (string): A unique, server-minted identifier formatted as a UUID, with no type prefix.
- **`created_at`** (string): An ISO 8601 UTC timestamp with three fractional digits (e.g., `2025-05-24T10:30:00.123Z`) recorded when the resource is first created.
- **`updated_at`** (string): An ISO 8601 UTC timestamp, in the same format, recorded when the resource is last modified. Any mutation to a resource's stored fields — including server-driven reconciliations of derived fields — refreshes this value.
- **`version`** (integer): A system-managed integer that begins at the resource's first persisted value and increments by one on every mutation of the resource. It is also the token used for optimistic concurrency control where applicable.

These four fields are present on `Customer`, `ServiceLevel`, `GradingStandard`, `Submission`, `SubmissionItem`, `IntakeRecord`, `GradeAssessment`, `AuthenticationCheck`, `Slab`, `PopulationReport`, `InsurancePolicy`, `RegradeRequest`, and `Shipment`. The single exception is the `Label` resource: a label is immutable once printed, so it carries only `id` and `created_at` — it has no `updated_at` and no `version`.

### 2.5. Nested Resource Retrieval and Existence Ordering

Many endpoints address a resource through a hierarchical path — for example, a path that names a submission item and then a sub-resource hanging off it. The system validates every identifier in the path from left to right and rejects the request with `ERR_NOT_FOUND` at the first identifier that does not correspond to an existing resource, before evaluating anything further to its right. The same rule governs foreign-key identifiers carried in a request body: each referenced resource must exist, and a reference to a non-existent resource yields `ERR_NOT_FOUND`. Existence is checked after authentication and role authorization but before any state, ownership, or business-rule evaluation.

### 2.6. Validation Ordering

When several checks guard one operation, they are evaluated in a fixed priority so that the same failing request always returns the same error. The global ordering is: first, authentication of the request headers (`ERR_UNAUTHENTICATED`); then role authorization (`ERR_FORBIDDEN_ROLE`); then existence of every referenced resource, left to right (`ERR_NOT_FOUND`); then customer ownership of the referenced submission or item (`ERR_NOT_OWNER`); then whether the target resource is in a valid state for the requested transition (`ERR_INVALID_STATE`); then, for a regrade request, the optimistic-concurrency version check (`ERR_STALE_ITEM_VERSION`); and finally the operation-specific business rules described throughout §2 and §3. Where a single operation carries more than one business rule, the per-operation ordering is stated alongside that operation's workflow. Two generic failures sit beneath the domain rules: a malformed body, a missing required field, or an invalid enum value is rejected with `ERR_INVALID_REQUEST`, and a semantically invalid field value that is otherwise well-formed (for example a non-positive `declared_value_cents`) is rejected with `ERR_VALIDATION`.

### 2.7. Monetary Precision and Rounding

All monetary amounts in the system are stored and returned as whole integer cents; there are no fractional cents and no floating-point money. Insurance amounts are the only computed monetary figures that require rounding, and they are always rounded **up** to the next whole cent (ceiling) — never down and never to nearest. The precise point at which the ceiling is applied differs between the per-item estimate and the aggregate premium, and that difference is intentional; the exact evaluation order for each is specified in §3 where those figures are computed. Grades, by contrast, are expressed on a half-point lattice and are always rounded **down** to the nearest half point (floor); grade rounding is described with the grading calculations in §3.

### 2.8. Optimistic Concurrency Control on Regrade

A crack-and-regrade is the one operation in this system that takes an explicit concurrency token. Opening a regrade request against a submission item must carry `expected_item_version`, a non-optional field whose value is the `version` of the target `SubmissionItem` that the client last observed. The server compares `expected_item_version` against that item's current `version`. If another writer has already opened a regrade request against the same item — cracking its active slab and advancing the item's `version` — the value the current client holds is stale and no longer matches, so the request is rejected with `ERR_STALE_ITEM_VERSION` (HTTP 412). This prevents a client from cracking and superseding a slab it has not actually observed. No other endpoint accepts or requires a version field; only the regrade-request creation is version-guarded.

### 2.9. Hierarchical Posture and Cascade Consistency

A `Submission`'s `status` is never set directly by a client. It is a computed posture re-derived from the states of its child `SubmissionItem` records every time a child changes, and the parent's `updated_at` and `version` advance whenever that re-derivation changes the stored posture. The precise rules that map child item states to the parent posture — and the symmetric rules that move items between states — are given in §3. Likewise, several single operations mutate more than one entity at once: encapsulating an item mints a slab, bumps a population census bucket, finalizes that item's fee, and may advance the parent submission's posture; cracking a slab decrements a census bucket, supersedes a grade assessment, and increments the item's version; reporting a shipment lost files and pays an insurance claim and credits the customer's wallet. Each of these cascades is specified in full in the workflow subsections that follow, and every entity touched by a cascade has its own `updated_at` and `version` advanced as part of the same operation.

### 2.10. The Population Census Principle

The system maintains a live **population census**: for every combination of grading standard, normalized collectible title, and discrete grade, a `PopulationReport` bucket counts how many active (non-cracked) slabs currently exist. The census is a conserved quantity. Sealing an item into a slab increments exactly one bucket by one; cracking that slab in a regrade decrements exactly that same bucket by one. A census count never drops below zero. Because a regrade can land an item at a different grade than before, the bucket that is decremented on crack and the bucket that is incremented on re-encapsulation need not be the same; the net effect across a full crack-and-regrade cycle is zero only once the item has been re-sealed. The exact bucket key and the increment/decrement timing are described with the encapsulation and regrade workflows in §3.

## 3. Business Logic & Workflows

### 3.1. Catalog Configuration: Service Levels and Grading Standards

Before any submission can be created, a `LabAdmin` configures the two catalog dimensions that every submission references.

A **service level** is a turnaround tier. It is created with a short `code` (such as ECONOMY, REGULAR, EXPRESS, or WALKTHROUGH), which must be unique and non-empty; a promised `turnaround_business_days`, which must be at least 1; a per-item `base_fee_cents`, which must be zero or greater; a `max_declared_value_cents`, the inclusive upper cap on the declared value any single item may carry at this tier, which must be at least 1; and an `insurance_rate_bps`, the insurance rate expressed in basis points where one basis point is one hundredth of one percent, which must be zero or greater. A service level also carries an `active` flag indicating whether new submissions may select the tier; when the flag is omitted at creation it defaults to true. The service-level listing may be filtered by the `active` flag.

A **grading standard** defines a grade scale and the weighting used to roll four subgrades into one overall grade. It is created with a unique, non-empty `code` (such as CARD_10PT or COMIC_10PT); a `max_grade` greater than zero that is the top of the scale, such as 10.0; an `authentic_min_grade`, the inclusive minimum overall grade at or above which an item is deemed gradeable-authentic and receives a numeric grade (it must be greater than zero and no greater than `max_grade`); and four weighting fields — `centering_weight_bps`, `corners_weight_bps`, `edges_weight_bps`, and `surface_weight_bps` — each expressed in basis points of ten thousand and each zero or greater. The four weights must sum to exactly 10000 basis points; a standard whose `centering_weight_bps`, `corners_weight_bps`, `edges_weight_bps`, and `surface_weight_bps` do not add up to exactly 10000 is rejected with `ERR_WEIGHTS_NOT_NORMALIZED`. An overall grade strictly below `authentic_min_grade` does not earn a number; it instead produces an authentic-only label, as described in §3.5.

### 3.2. Building and Submitting a Submission

A person becomes a `Customer` by registering with a unique, non-empty `email` and a display `full_name`; registration initializes the customer's wallet `store_credit_cents` to zero. A `Customer` then opens a **submission** as a working draft by naming the owning customer through `customer_id` and the chosen turnaround tier through `service_level_id`. A new submission begins in `DRAFT` status with an `item_count` of zero; its computed fee totals `total_estimated_fee_cents` and `total_final_fee_cents` both begin at zero. While the submission remains in `DRAFT`, the customer adds items to it and may remove them.

Each **submission item** added to a draft is described by the grading scale it will be graded on (`grading_standard_id`), a human-readable `title` such as "1986 Fleer Jordan #57", and a `declared_value_cents` of at least 1 representing the customer's stated value of the piece. The item's parent batch is recorded through `submission_id`. A freshly added item begins in `REGISTERED` status; its `estimated_fee_cents` and `final_fee_cents` start at zero, its `regrade_count` starts at zero, and its `current_grade` is null until a grade is first finalized. Adding an item raises the parent's `item_count` by one. Items may be added or removed only while the parent submission is in `DRAFT`; an attempt to add or remove an item once the submission has left `DRAFT` is rejected with `ERR_SUBMISSION_FROZEN`. Removing an item from a draft lowers the parent's `item_count` by one.

Submitting a draft is the customer's commitment. The submit operation first requires that the submission contain at least one item: a submit attempt on a submission whose `item_count` is zero is rejected with `ERR_EMPTY_SUBMISSION`. It then requires that every item's `declared_value_cents` be less than or equal to the submission tier's `max_declared_value_cents`; if any item's declared value exceeds the tier cap, the submit is rejected with `ERR_DECLARED_VALUE_EXCEEDS_TIER`. Between these two checks the empty-submission check is evaluated first. When both pass, the submission advances `DRAFT → SUBMITTED`, its item set is frozen, the estimated fee total is pinned, and an insurance policy is created for the batch. The fee and insurance computations performed at this moment are detailed in §3.8 and §3.9. Only the owning customer — the one whose `id` equals the `customer_id` on the submission — may submit it.

### 3.3. Intake: Receiving and Verifying Items

Once a submission has been submitted, the lab's warehouse begins receiving the physical items. A `Receiver` logs **intake** for a registered item, supplying a free-text `condition_note` describing the item's physical state on arrival and a boolean `matches_declaration` recording whether the received piece matches the customer's declared title and value. Logging intake is permitted only while the parent submission is in either `SUBMITTED` or `RECEIVING` status, and only when no intake record already exists for that item; a second intake attempt on the same item is rejected with `ERR_DUPLICATE_INTAKE`. Logging intake creates an `IntakeRecord` whose `item_id` references the received item, stamps `received_at` from the server's logical clock — this stamp is the start of that item's SLA window — and records the acting receiver's opaque id in `received_by_user_id`. The item advances `REGISTERED → INTAKE_LOGGED`. When the first item of a submission is logged, the parent posture moves `SUBMITTED → RECEIVING`; logging further items leaves the posture unchanged.

If a received item does not match its declaration — that is, its `IntakeRecord.matches_declaration` is false — a `Receiver` may **reject** it. Rejection is permitted only on an item that has been intake-logged, and only when its intake record's `matches_declaration` is false. A rejected item advances `INTAKE_LOGGED → REJECTED_RETURNED`: it is excluded from grading and from insurance coverage, the submission's insurance covered value is recomputed to drop it (see §3.9), the parent posture is re-derived, and the item becomes eligible to be sent back to the customer in the return shipment without a slab.

### 3.4. Grading: Subgrades, Provisional and Final Overall

A `Grader` opens a **grade assessment** on an item whose intake matches its declaration. Grading is permitted only on an item that is in `INTAKE_LOGGED` status (with an intake record whose `matches_declaration` is true) or — in the regrade case described in §3.7 — in `CRACK_PENDING` status. The assessment records the standard used through `grading_standard_id` (a version snapshot of the standard pinned to this assessment, referenced together with the item through `item_id`) and four subgrades on the standard's scale: `centering_subgrade`, `corners_subgrade`, `edges_subgrade`, and `surface_subgrade`. Each subgrade must lie within the inclusive range from 0 to the standard's `max_grade`; a subgrade below 0 or above `max_grade` is rejected with `ERR_SUBGRADE_OUT_OF_RANGE`. Creating the first assessment on an item advances it `INTAKE_LOGGED → GRADING`, and when the first item of a submission enters `GRADING` the parent posture moves `RECEIVING → IN_GRADING`.

At assessment-create time the system computes the **provisional overall**, stored in `provisional_overall`. The provisional grade is optimistic: it is the weighted average of the four subgrades using the pinned standard's basis-point weights, then floored to the half-point lattice. Concretely, multiply each subgrade by its corresponding weight — `centering_subgrade` by `centering_weight_bps`, `corners_subgrade` by `corners_weight_bps`, `edges_subgrade` by `edges_weight_bps`, and `surface_subgrade` by `surface_weight_bps` — sum those four products, and divide the sum by 10000 to obtain the raw weighted value. Multiply the raw value by two, take the floor to the nearest whole number, and divide by two; the result is the provisional overall rounded down to the nearest half point. The provisional grade deliberately does not apply the lowest-subgrade cap.

A separate **finalize** step computes the **final overall**, stored in `final_overall`. The final grade is pessimistic: it starts from the same weighted-then-floored value used for the provisional grade, but then caps the result so the overall can never exceed the single lowest subgrade plus 1.5. Concretely, compute the weighted-floored value exactly as for the provisional grade; separately, take the smallest of the four subgrades; the capped value is the lesser of the weighted-floored value and that smallest subgrade plus 1.5; finally, multiply the capped value by two, take the floor, and divide by two to land it back on the half-point lattice. When the four subgrades are uneven — one materially lower than the others — the final overall falls below the provisional overall even though the inputs are identical, because the lowest-subgrade-plus-1.5 cap bites. An item must have an unsuperseded grade assessment whose `final_overall` has been computed before it can proceed to authentication.

### 3.5. Authentication and the Authentic-Only Boundary

Once an item's active assessment has been finalized, an `Authenticator` runs an **authentication check** on it. Authentication is permitted only on an item in `GRADING` status that has an unsuperseded grade assessment whose `final_overall` is non-null. The check records a `verdict` of `GENUINE`, `ALTERED`, or `COUNTERFEIT` against the item through `item_id`, captures the acting authenticator's opaque id in `authenticator_user_id`, and may carry a free-text `alteration_note`. When the verdict is `ALTERED` or `COUNTERFEIT`, the `alteration_note` is required and must be non-empty; a verdict of `ALTERED` or `COUNTERFEIT` submitted without an alteration note is rejected with `ERR_ALTERATION_NOTE_REQUIRED`. When the verdict is `GENUINE`, the note is optional and defaults to null. Running the check advances the item `GRADING → AUTHENTICATED`. A verdict of `ALTERED` or `COUNTERFEIT` means the item cannot be encapsulated as a graded piece; its label will read "NOT GENUINE".

The grade text a slab will eventually carry is determined at encapsulation by the relationship between the item's final overall grade and the standard's `authentic_min_grade`. If the assessment's final overall is at or above `authentic_min_grade` and the authentication verdict is `GENUINE`, the label shows the numeric grade (for example, "9.5"). If the verdict is `GENUINE` but the final overall is below `authentic_min_grade`, the item is gradeable-authentic without a number and the label reads "AUTHENTIC". If the verdict is `ALTERED` or `COUNTERFEIT`, the label reads "NOT GENUINE". This computed text is stored on the slab as `label_grade_text`.

### 3.6. Encapsulation: Minting the Slab, the Census, and the Final Fee

An `Authenticator` **encapsulates** an authenticated item into a slab, naming the assessment to be sealed through `assessment_id`. Encapsulation is permitted only on an item in `AUTHENTICATED` status that already has an authentication check, and only when no active slab already exists for the item. Two business guards apply in addition: an item whose authentication verdict is `COUNTERFEIT` cannot be encapsulated as a graded slab and is rejected with `ERR_COUNTERFEIT_NOT_ENCAPSULATABLE`; and because at most one active slab may exist per item, an encapsulation attempt on an item that already has an active slab is rejected with `ERR_ACTIVE_SLAB_EXISTS`.

A successful encapsulation performs several effects together. It creates a `Slab` referencing the item through `item_id` and the sealed assessment through `assessment_id`, sets the slab's `active` flag to true, and mints a globally unique `cert_number` — a server-generated certificate number printed on the slab that is never reused. It computes and stores the slab's `label_grade_text` per the authentic-only rules in §3.5. It then bumps the population census: it finds or creates the `PopulationReport` bucket keyed by the item's grading standard, the normalized title, and the grade, and increments that bucket's `pop_count` by one (see §3.10). It finalizes the item's fee into `final_fee_cents` and adds that amount to the submission's `total_final_fee_cents` (see §3.8). The item advances `AUTHENTICATED → ENCAPSULATED`, and the parent posture is re-derived: once every non-rejected item in the submission is `ENCAPSULATED` and no regrade request is still open, the submission moves `IN_GRADING → READY_TO_SHIP` and the submission's final fee total is computed (see §3.8).

A label may be printed for a slab. Printing a **label** records the slab through `slab_id` and the chosen population bucket through `population_report_id`, snapshots that bucket's `pop_count` at print time into `printed_pop_count` so the printed figure is immutable thereafter, and stamps `printed_at` from the logical clock. A label, once printed, is never modified.

### 3.7. Crack-and-Regrade

A `Customer` who owns a submission and believes a sealed item was undergraded may open a **regrade request** to crack the slab and send the item back through grading. The request names the item through `item_id`, the slab to be cracked through `prior_slab_id` (which must be the item's active slab), the OCC token `expected_item_version`, and a free-text `reason` such as "believe undergraded". A regrade request begins in `OPEN` status.

Several conditions guard the request, evaluated in the global order of §2.6. Ownership applies — only the customer who owns the submission may open the request, else `ERR_NOT_OWNER`. The item must currently have an active slab and therefore be in `ENCAPSULATED` status; a request against an item not in that state is rejected with `ERR_INVALID_STATE`. The optimistic-concurrency check then applies: `expected_item_version` must equal the item's current `version`, and a mismatch is rejected with `ERR_STALE_ITEM_VERSION` (HTTP 412), as described in §2.8. Finally, a regrade is not allowed once the submission has left the shop: if the parent submission is already `SHIPPED` (or `CLOSED`), the request is rejected with `ERR_SUBMISSION_ALREADY_SHIPPED`.

When the request is accepted, the item advances `ENCAPSULATED → CRACK_PENDING` and a cascade fires. The request is created with status `OPEN`, the prior slab is marked cracked by setting its `active` flag to false, and the request transitions to `CRACKED`. The population census bucket that counted the cracked slab is decremented by one (see §3.10). The item's previously active grade assessment is marked superseded by setting its `superseded` flag to true. The item's `version` is incremented by one — this is precisely the increment that makes any concurrently held `expected_item_version` stale. The parent posture is re-derived back to `IN_GRADING`, since the item has re-entered the pipeline.

From `CRACK_PENDING`, a `Grader` opens a new grade assessment exactly as in §3.4; this re-entry is permitted only when the item has an open or cracked regrade request and the prior slab's `active` flag is false. Creating that new assessment advances the item `CRACK_PENDING → GRADING`, computes a fresh `provisional_overall`, sets the regrade request's status to `COMPLETED`, and increments the item's `regrade_count` by one. The item then re-runs the same grading, authentication, and encapsulation edges; the re-encapsulation re-bumps the census, possibly into a different bucket if the new grade differs, and the regrade surcharge described in §3.8 is applied to the item's final fee.

### 3.8. Fees: Estimate at Submit, Final at Encapsulate

Fees are quoted twice, and the two figures diverge by design.

At submit, each item's **estimate** is pinned into its `estimated_fee_cents`. The estimate is the tier's `base_fee_cents` plus an estimated insurance charge computed on the item's full, **uncapped** declared value: multiply `declared_value_cents` by `insurance_rate_bps`, divide by 10000, and round the result up to the next whole cent (ceiling); add that estimated insurance to the base fee. The submission's `total_estimated_fee_cents` is then the sum of the per-item estimates, with the rounding order pinned: each item's insurance is ceiled first and the already-ceiled per-item estimates are then summed. No regrade surcharge appears in the estimate.

At encapsulation, each item's **final fee** is computed into its `final_fee_cents`. The final fee is the tier's `base_fee_cents`, plus a final insurance charge computed on the **capped** declared value, plus a regrade surcharge. The capped value is the lesser of the item's `declared_value_cents` and the tier's `max_declared_value_cents`; the final insurance is that capped value multiplied by `insurance_rate_bps`, divided by 10000, and rounded up to the next whole cent (ceiling). The regrade surcharge is the item's `regrade_count` multiplied by 1500 cents per completed regrade cycle. The final fee therefore equals base plus final insurance plus surcharge. The final fee diverges from the estimate whenever the declared value exceeded the tier cap (final insurance is computed on the smaller capped value) or whenever the item was regraded (the surcharge applies).

When a submission reaches `READY_TO_SHIP`, the submission's `total_final_fee_cents` is computed as the sum of the `final_fee_cents` of only those items whose status is `ENCAPSULATED`; rejected items (`REJECTED_RETURNED`) contribute zero because no grading fee was earned on them. As with the estimate, each per-item insurance figure is already ceiled before the items are summed.

### 3.9. Insurance: Coverage, Premium, and Loss Payout

Submitting a submission creates one **insurance policy** for the batch, referencing the submission through `submission_id`. The policy's `covered_value_cents` is the sum, over every item whose status is not `REJECTED_RETURNED`, of that item's declared value capped at the tier's `max_declared_value_cents` — that is, for each such item take the lesser of its `declared_value_cents` and the tier cap, then add those capped amounts together. The policy's `premium_cents` is computed by multiplying the aggregate `covered_value_cents` by the tier's `insurance_rate_bps`, dividing by 10000, and rounding the single aggregate result up to the next whole cent (ceiling). Note the deliberate contrast with the per-item estimate insurance of §3.8: the premium here is sum-then-ceil (the covered values are summed first, then the rate is applied and ceiled once on the aggregate), whereas the per-item estimate insurance is ceil-then-sum. The policy's `claim_status` begins at `NONE` and its `payout_cents` begins at zero. When an item is rejected at intake, the policy's covered value is recomputed to exclude it.

A loss is the compensating path. If a dispatched shipment is reported lost, the policy's `claim_status` first moves to `FILED`, then the payout is computed as exactly the policy's `covered_value_cents`, that amount is recorded in `payout_cents`, the `claim_status` advances to `PAID`, and the customer's wallet `store_credit_cents` is increased by exactly that payout. The invariant is strict: the customer's `store_credit_cents` rises by exactly the policy's `covered_value_cents` — no more and no less. The shipment's own `insured_value_cents` is a copy of the policy's `covered_value_cents` taken at dispatch, and may also be surfaced as the shipment's coverage figure.

### 3.10. The Population Census in Detail

The population census is organized into `PopulationReport` buckets, each identified by the combination of a grading standard (`grading_standard_id`), a normalized `title_key` (for example, "1986-FLEER-JORDAN-57"), and a discrete `grade_value`. The triple of grading standard, title key, and grade value is unique. The `grade_value` is the item's final overall grade when the item is gradeable-authentic; when the item is authentic-only without a number, the bucket's `grade_value` is the sentinel -1, which denotes the AUTHENTIC-only bucket. Each bucket's `pop_count` counts the active, non-cracked slabs in it.

On encapsulation, the system finds or creates the bucket for the item's standard, normalized title key, and grade value, and increments that bucket's `pop_count` by one. On crack, the system finds the bucket the cracked slab was counted in — keyed by that slab's standard, title key, and grade value — and decrements its `pop_count` by one; a count never falls below zero. Because a regrade may produce a different grade, the bucket decremented on crack and the bucket incremented on the subsequent re-encapsulation are not necessarily the same bucket; the census returns to its prior aggregate only after the item has been re-sealed.

### 3.11. Return Shipment, Delivery, Loss, and Closure

When a submission is `READY_TO_SHIP`, a `LabAdmin` creates a **return shipment** for it, supplying the `carrier` — one of `UPS`, `FEDEX`, or `USPS` — and the `tracking_number`. The shipment references the submission through `submission_id`, begins in `LABEL_CREATED` status, and copies its `insured_value_cents` from the submission's insurance policy covered value. Creating a shipment requires the parent submission to be `READY_TO_SHIP`.

Dispatching the shipment advances it `LABEL_CREATED → IN_TRANSIT`, moves the submission `READY_TO_SHIP → SHIPPED`, and moves every covered item to `SHIPPED` — both encapsulated items and any rejected items returned in the same shipment reach the terminal `SHIPPED` state. Dispatch also re-copies `insured_value_cents` from the policy's covered value. From `IN_TRANSIT`, the shipment either reaches `DELIVERED` when delivery is confirmed, or branches to `LOST` when the shipment is reported lost. Marking the shipment delivered advances it `IN_TRANSIT → DELIVERED` and makes the submission eligible to be closed. Reporting the shipment lost advances it `IN_TRANSIT → LOST` and triggers the insurance loss cascade of §3.9 — filing and paying the claim and crediting the customer's wallet.

Finally, a `LabAdmin` closes a delivered submission, advancing it `SHIPPED → CLOSED`; closure requires the shipment to have reached `DELIVERED` and archives the submission against further mutation.

### 3.12. The Logical Clock

The server runs on a logical clock rather than wall-clock time, so that SLA-window math and timestamps are deterministic during testing. The clock's startup default is 2026-01-01T00:00:00Z and it never falls back to wall-clock time. An administrative test-driving capability sets the clock to a supplied instant carried in `to_iso8601`; once set, the clock supplies the `received_at` stamp written at intake and the `printed_at` stamp written when a label is printed. This capability is available to the `LabAdmin` role and, like customer registration, may also be exercised without authentication.

## 4. Endpoint Definitions

Operations that create a new, distinct resource return a `201 Created` status code. Operations that modify or transition an existing resource return a `200 OK` status code, except item removal, which returns `204 No Content`. The request and response bodies for each operation are not tabulated here; reconstruct them from the workflow narratives in §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/customers` | Register a customer | Anonymous |
| GET | `/customers/{id}` | Fetch a customer (wallet balance) | Customer, LabAdmin |
| POST | `/service-levels` | Create a turnaround tier | LabAdmin |
| GET | `/service-levels/{id}` | Fetch a service level | LabAdmin, Customer |
| GET | `/service-levels` | List service levels | LabAdmin, Customer |
| POST | `/grading-standards` | Create a grading standard | LabAdmin |
| GET | `/grading-standards/{id}` | Fetch a grading standard | LabAdmin, Grader, Customer |
| POST | `/submissions` | Create a DRAFT submission | Customer |
| GET | `/submissions/{id}` | Fetch a submission (computed posture & fee totals) | Customer, LabAdmin, Receiver, Grader, Authenticator |
| GET | `/submissions` | List/query submissions | Customer, LabAdmin |
| POST | `/submissions/{id}/submit` | Submit a draft; freeze items, compute estimate, create insurance | Customer |
| POST | `/submissions/{id}/items` | Add an item to a DRAFT submission | Customer |
| GET | `/submissions/{id}/items` | List items of a submission | Customer, LabAdmin, Receiver, Grader, Authenticator |
| GET | `/submission-items` | List/query items | Customer, LabAdmin, Receiver, Grader, Authenticator |
| GET | `/submission-items/{id}` | Fetch a submission item | Customer, LabAdmin, Receiver, Grader, Authenticator |
| DELETE | `/submission-items/{id}` | Remove an item from a DRAFT submission | Customer |
| POST | `/submission-items/{id}/intake` | Log intake for a received item | Receiver |
| GET | `/submission-items/{id}/intake` | List intake records for an item | Receiver, LabAdmin, Customer |
| POST | `/submission-items/{id}/reject` | Reject an item that does not match declaration | Receiver |
| POST | `/submission-items/{id}/grade-assessments` | Create a grade assessment (also the regrade re-entry) | Grader |
| GET | `/submission-items/{id}/grade-assessments` | List grade assessments for an item | Grader, Authenticator, LabAdmin, Customer |
| GET | `/grade-assessments` | List/query grade assessments | Grader, Authenticator, LabAdmin, Customer |
| GET | `/grade-assessments/{id}` | Fetch a grade assessment | Grader, Authenticator, LabAdmin, Customer |
| POST | `/grade-assessments/{id}/finalize` | Finalize an assessment; compute final overall | Grader |
| POST | `/submission-items/{id}/authentication` | Run authentication | Authenticator |
| GET | `/submission-items/{id}/authentication` | List authentication checks for an item | Authenticator, LabAdmin, Customer |
| POST | `/submission-items/{id}/encapsulate` | Encapsulate the item into a slab | Authenticator |
| GET | `/submission-items/{id}/slabs` | List slabs for an item (incl. cracked) | Authenticator, LabAdmin, Customer |
| GET | `/slabs` | List/query slabs | Authenticator, LabAdmin, Customer |
| GET | `/slabs/{id}` | Fetch a slab | Authenticator, LabAdmin, Customer |
| POST | `/slabs/{id}/label` | Print the label for a slab | Authenticator, LabAdmin |
| GET | `/slabs/{id}/label` | List labels for a slab | Authenticator, LabAdmin, Customer |
| GET | `/labels` | List/query labels | Authenticator, LabAdmin, Customer |
| GET | `/labels/{id}` | Fetch a label | Authenticator, LabAdmin, Customer |
| GET | `/population-reports` | List/query population buckets | LabAdmin, Customer, Authenticator |
| GET | `/population-reports/{id}` | Fetch a single population bucket | LabAdmin, Customer, Authenticator |
| GET | `/submissions/{id}/insurance-policy` | Fetch the submission's insurance policy | Customer, LabAdmin |
| POST | `/submission-items/{id}/regrade-requests` | Crack-and-regrade (OCC on item version) | Customer |
| GET | `/submission-items/{id}/regrade-requests` | List regrade requests for an item | Customer, LabAdmin, Grader |
| GET | `/regrade-requests` | List/query regrade requests | Customer, LabAdmin, Grader |
| GET | `/regrade-requests/{id}` | Fetch a regrade request | Customer, LabAdmin, Grader |
| POST | `/submissions/{id}/shipments` | Create a return shipment | LabAdmin |
| GET | `/submissions/{id}/shipments` | List shipments for a submission | LabAdmin, Customer |
| GET | `/shipments/{id}` | Fetch a shipment | LabAdmin, Customer |
| POST | `/shipments/{id}/dispatch` | Dispatch the shipment | LabAdmin |
| POST | `/shipments/{id}/deliver` | Mark delivered | LabAdmin |
| POST | `/shipments/{id}/report-lost` | Report shipment lost; file & pay claim | LabAdmin |
| POST | `/submissions/{id}/close` | Close a delivered submission | LabAdmin |
| POST | `/_clock/set_current_utc` | Set the server logical clock | LabAdmin, Anonymous |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_OWNER` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_ITEM_VERSION` | 412 |
| `ERR_ALTERATION_NOTE_REQUIRED` | 422 |
| `ERR_COUNTERFEIT_NOT_ENCAPSULATABLE` | 422 |
| `ERR_SUBGRADE_OUT_OF_RANGE` | 422 |
| `ERR_WEIGHTS_NOT_NORMALIZED` | 422 |
| `ERR_ACTIVE_SLAB_EXISTS` | 409 |
| `ERR_SUBMISSION_ALREADY_SHIPPED` | 409 |
| `ERR_DECLARED_VALUE_EXCEEDS_TIER` | 422 |
| `ERR_EMPTY_SUBMISSION` | 422 |
| `ERR_SUBMISSION_FROZEN` | 409 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_VALIDATION` | 422 |
| `ERR_DUPLICATE_INTAKE` | 409 |
| `ERR_PAGINATION_INVALID` | 400 |
