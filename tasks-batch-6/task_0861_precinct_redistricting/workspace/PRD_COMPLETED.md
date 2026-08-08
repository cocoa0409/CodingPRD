# Precinct Redistricting API — Product Requirements Document

## 1. Introduction

Every decade, and often between decades as populations shift, local election authorities must redraw the boundaries of legislative districts and the operational precincts that carry out elections. The work is unforgiving: districts must be as close to equal in population as the law allows, minority voting strength must be protected under the Voting Rights Act, communities of interest must be respected, and the whole exercise must survive public scrutiny through comment periods and hearings before a plan is adopted and handed to the mapping systems that run elections. Getting any of the arithmetic wrong — a district that deviates too far from the ideal population, a plan adopted by the very person who drew it, a polling place quietly overbooked past its capacity — produces litigation and disenfranchisement.

This document specifies a REST API for managing that entire process. The system tracks jurisdictions and their census-block reference data, lets cartographers assemble competing redistricting plans by partitioning census blocks into districts, evaluates each plan against population-deviation and VRA thresholds, drives a plan through review, public comment, hearings, and adoption, and manages the operational layer of precincts, polling places, and early-voting assignments. Multiple plans (scenarios) may coexist and be compared side by side; adopting one supersedes the rest. The design deliberately separates the people who draw plans from the people who approve them, and it uses optimistic concurrency to keep two editors from silently clobbering each other's work.

The reader of this document is the engineer building the service. Business intent comes first and the mechanical contract second; where a rule matters to correctness, it is stated precisely and without hedging.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming that user's role. If either header is missing, or if `X-User-Role` is not one of the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are well-formed but the role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

There are exactly five roles, spelled precisely as follows:

- **`Cartographer`** — draws plans: manages jurisdictions, census-block reference data, plans, districts, and block assignments, and submits a draft plan for review.
- **`Demographer`** — runs VRA, deviation, and contiguity compliance checks and may send a hearing-stage plan back for revision.
- **`CommissionChair`** — chairs the commission: opens the comment period, schedules, holds, and cancels hearings, dispositions comments, and rejects or adopts plans.
- **`ElectionClerk`** — manages precincts, polling places, venues, polling assignments, and GIS exports.
- **`PublicParticipant`** — a member of the public who submits comments during the comment period.

Every role's `X-User-ID` is an **opaque operator identifier** not tied to any persisted entity; the server never compares it to any entity's `id` for ownership purposes. It is, however, recorded where a business rule demands it: when a `Cartographer` creates a plan, the server stamps that user's `X-User-ID` onto the plan as `created_by_user_id`, and that recorded value later powers the four-eyes rule at adoption (see §2.10 and §3.5). All five roles may call every `GET` endpoint. The `Cartographer`, `Demographer`, `CommissionChair`, and `ElectionClerk` roles may set the logical clock; `PublicParticipant` may not.

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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits, and reflects the current logical-clock instant (§2.5) rather than wall-clock time.
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

All list endpoints accept two query parameters: `limit` and `offset`. `limit` defaults to 10, with a minimum of 1 and a maximum of 100; a requested value above 100 is capped at 100. `offset` defaults to 0 and has no upper bound beyond the size of the collection. List results are always ordered by `created_at` ascending (oldest first), with ties broken by creation order (oldest-created first). The `meta` block of a list response reports `limit`, `offset`, `total_count` (the total number of matching records before pagination), and `has_more` (true when records remain beyond the current page).

### 2.4. Resource Identity, Timestamps, and Versioning

Every resource is assigned a server-minted `id` — an opaque UUID with no type prefix — at creation. Most resources also carry three common fields: `created_at` and `updated_at`, both ISO 8601 UTC timestamps with three fractional digits, and `version`, an integer that begins at 1 and increments by exactly 1 on every mutation of the resource. `created_at` is fixed at creation; `updated_at` advances to the logical-clock instant of each mutation.

One resource is an exception: a **`ComplianceCheck`** is an immutable snapshot. It carries only `id` and `created_at` — it has neither `updated_at` nor `version`, because it is never mutated after creation. All other resources described in this document (jurisdictions, census blocks, plans, districts, block assignments, precincts, polling places, polling assignments, venues, hearings, public comments, and GIS exports) carry the full set of common fields.

### 2.5. The Logical Clock

The system runs on a **logical clock** rather than wall-clock time, so that time-dependent rules are deterministic and testable. At startup the clock reads exactly `2026-05-01T00:00:00Z`, and until it is explicitly set it holds that value — it never falls back to the machine's real time. An administrative test-driving capability accepts a `to_iso8601` instant and moves the clock to it; every subsequent time-sensitive rule (hearing hold eligibility, `comment_opened_at`, `adopted_at`, and the `updated_at` on any mutation) reads from this clock.

### 2.6. Population Balance, Deviation Standards, and Precision

The central measure of a good plan is how evenly it distributes population. The equal-population target is the jurisdiction's `ideal_district_population`, computed as the jurisdiction's `total_population` divided by its `target_district_count` as an exact quotient, stored and reported to 4 decimal places using round-half-up. Each district's `deviation_pct` measures how far that district's assigned population strays from the ideal, and is reported to 2 decimal places using round-half-up.

The system reports population balance under **two distinct legal standards from the same inputs**, and the difference matters:

- The **max-absolute-deviation** standard, `max_abs_deviation_pct`, is the largest absolute district deviation. A plan whose most over-populated district is +4.9% and whose most under-populated district is −4.9% scores **4.90** under this standard.
- The **overall-range** standard, `overall_deviation_range_pct`, is the spread between the most over- and most under-populated districts — the maximum district deviation minus the minimum district deviation. That same +4.9%/−4.9% plan scores **9.80** under this standard: a different number from identical inputs.

Both plan-level figures are reported to 2 decimal places, round-half-up. Wherever this document specifies rounding, it means round-half-up unless it explicitly says otherwise; monetary-style truncation is never used.

### 2.7. Optimistic Concurrency Control

Two operations mutate a shared parent whose prior state a stale editor could silently overwrite, and both are guarded by optimistic concurrency control keyed on the parent's `version`.

Creating a block assignment within a plan requires an `expected_plan_version` field carrying the plan `version` the client last observed. Because a new assignment for a census block supersedes that block's prior active assignment, a client holding a stale view of the plan would overwrite an assignment change it never saw. If `expected_plan_version` does not equal the plan's current `version`, the create is rejected with `ERR_STALE_PLAN_VERSION` (HTTP 412).

Likewise, creating a polling assignment for a precinct requires an `expected_precinct_version` field carrying the precinct `version` the client last observed. A new polling assignment supersedes the precinct's prior active one, so a stale writer would clobber a reassignment it never observed. If `expected_precinct_version` does not equal the precinct's current `version`, the create is rejected with `ERR_STALE_PRECINCT_VERSION` (HTTP 412). No other endpoint accepts or requires a version field.

### 2.8. Nested Paths and Referential Integrity

Many resources are addressed through nested paths — a census block under a jurisdiction, districts and block assignments and hearings under a plan. Path identifiers are validated left to right: the outer resource must exist before the inner one is examined. A missing jurisdiction yields `ERR_JURISDICTION_NOT_FOUND`, a missing plan `ERR_PLAN_NOT_FOUND`, a missing district `ERR_DISTRICT_NOT_FOUND`, a missing precinct `ERR_PRECINCT_NOT_FOUND`, a missing polling place `ERR_POLLING_PLACE_NOT_FOUND`, a missing polling assignment `ERR_POLLING_ASSIGNMENT_NOT_FOUND`, a missing hearing `ERR_HEARING_NOT_FOUND`, a missing comment `ERR_COMMENT_NOT_FOUND`, a missing block assignment `ERR_BLOCK_ASSIGNMENT_NOT_FOUND`, and a missing export `ERR_EXPORT_NOT_FOUND` — each HTTP 404.

Foreign keys carried in a request body are validated the same way after the path is resolved. An unknown `district_id` yields `ERR_DISTRICT_NOT_FOUND`; an unknown `census_block_id` yields `ERR_CENSUS_BLOCK_NOT_FOUND`; an unknown `polling_place_id` or venue reference yields `ERR_POLLING_PLACE_NOT_FOUND`; an unknown `parent_plan_id` yields `ERR_PLAN_NOT_FOUND`; an unknown `target_precinct_id` yields `ERR_PRECINCT_NOT_FOUND` — all HTTP 404.

Beyond mere existence, cross-aggregate references must be internally consistent (HTTP 422): a `district_id` named in a block assignment must belong to the same plan named in the path, or the request is rejected with `ERR_DISTRICT_PLAN_MISMATCH`; a `census_block_id` must belong to the plan's jurisdiction, or `ERR_BLOCK_JURISDICTION_MISMATCH`; a merge `target_precinct_id` must be in the same jurisdiction as the precinct being merged, or `ERR_PRECINCT_JURISDICTION_MISMATCH`; and a hearing venue must belong to the plan's jurisdiction, or `ERR_VENUE_JURISDICTION_MISMATCH`.

### 2.9. Cascades, Supersession, and Derived-Field Reconciliation

Many computed fields are **reconciled** rather than stored independently: a district's `assigned_population` and its deviation and minority metrics are always recomputed from the district's currently active block assignments, a plan's deviation and VRA metrics are recomputed from its districts, and a polling place's utilization is recomputed from its active polling assignments. Whenever an operation changes an underlying assignment, the affected parent's derived fields are recomputed in the same operation, and the parent's `version` and `updated_at` advance accordingly.

Supersession is the system's mechanism for keeping a single active view while preserving history. Assigning a census block that already has an active assignment does not duplicate it — the prior assignment moves to `SUPERSEDED` and the new one is `ACTIVE`. Assigning a precinct to a new polling place supersedes its prior active polling assignment the same way. And adopting one plan supersedes every competing plan in the jurisdiction. These cascades are detailed in §3.

### 2.10. Segregation of Duties

The people who draw plans and the people who approve them must be different people. This four-eyes principle is enforced at adoption: the `X-User-ID` adopting a plan must differ from the plan's recorded `created_by_user_id`. An attempt by the plan's own creator to adopt it is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403), even when every other adoption precondition is satisfied.

### 2.11. Validation Order

When a request could fail several checks at once, the checks are evaluated in a fixed priority order and the first failure is the one reported. The order is: (1) authentication — headers present and role recognized (`ERR_UNAUTHENTICATED`); (2) authorization — the role may call this endpoint (`ERR_UNAUTHORIZED`); (3) existence of every path id, left to right (the `*_NOT_FOUND` family); (4) existence of every body foreign key; (5) state — the target resource is in a state that permits the transition (`ERR_INVALID_STATE`); (6) cross-aggregate referential consistency (the `*_MISMATCH` family); (7) uniqueness and partition constraints (`ERR_DUPLICATE_DISTRICT_NUMBER`, `ERR_DUPLICATE_GEOID`, `ERR_INCOMPLETE_PARTITION`); (8) temporal-overlap constraints (`ERR_VENUE_TIME_CONFLICT`, `ERR_EV_WINDOW_CONFLICT`); (9) polling capacity (`ERR_POLLING_CAPACITY_EXCEEDED`); (10) segregation of duties (`ERR_SEGREGATION_OF_DUTIES`); (11) the plan-compliance gate at adoption (`ERR_PLAN_NOT_COMPLIANT`); (12) field-level validity such as enum membership, non-negative counts, and date ordering (`ERR_VALIDATION`, `ERR_INVALID_DATE_RANGE`); and (13) optimistic-concurrency version match (`ERR_STALE_PLAN_VERSION`, `ERR_STALE_PRECINCT_VERSION`). A lower-numbered failure always masks a higher-numbered one — for example, an unauthorized caller is told `ERR_UNAUTHORIZED` before any body field is examined.

## 3. Business Logic & Workflows

### 3.1. Establishing a Jurisdiction and Its Census Data

Everything begins with a jurisdiction. A `Cartographer` creates one by supplying its `name`, its two-letter USPS `state_code`, and the `target_district_count` — the number of districts a plan for this jurisdiction must produce, which must be at least 1. The creator may also supply `required_majority_minority_districts`, the VRA floor giving the minimum number of majority-minority districts a compliant plan must contain; it must be zero or greater and defaults to 0 when omitted. At creation the jurisdiction's computed totals — `total_population`, `voting_age_population_total`, and `ideal_district_population` — all start at 0.

Census blocks are the atomic population units. A `Cartographer` adds a block under a jurisdiction by supplying its `geoid` (the Census GEOID, which serves as the block's business key and must be unique within the jurisdiction — a repeat yields `ERR_DUPLICATE_GEOID`), its total `population`, its `voting_age_population`, its any-part `minority_vap` (the minority voting-age population used for VRA math), and its `registered_voters` (the certified count on file). Population and all demographic counts must be non-negative; additionally `voting_age_population` may not exceed `population`, and `minority_vap` may not exceed `voting_age_population` — any violation is `ERR_VALIDATION`. A newly created block has no precinct: its `precinct_id` is null until it is placed in one. The server stamps each block's `jurisdiction_id` from the path.

Adding a block reconciles the jurisdiction's aggregates. Across every census block whose `jurisdiction_id` matches, the jurisdiction's `total_population` becomes the sum of their `population`, its `voting_age_population_total` becomes the sum of their `voting_age_population`, and its `ideal_district_population` becomes `total_population` divided by `target_district_count` as an exact quotient rounded to 4 decimal places. Census blocks have no lifecycle, so every block in the jurisdiction always counts toward these sums. Blocks can be read individually or listed with an optional `jurisdiction_id` filter or an optional `precinct_id` filter to find the blocks currently in a given precinct.

### 3.2. Drafting a Plan: Districts and Block Assignments

A `Cartographer` opens a redistricting effort by creating a plan under a jurisdiction, giving it a `name` (a scenario label). The plan starts in `DRAFT`, and the server records the creating user's identifier as `created_by_user_id` and stamps `jurisdiction_id` from the path. A plan may instead be forked from an existing scenario by supplying a `parent_plan_id`: on a forked create, every `District` of the parent and every `ACTIVE` block assignment of the parent are deep-copied into the new plan, giving the cartographer a starting point to vary. A fresh plan omits `parent_plan_id`. Plans can be listed with an optional `jurisdiction_id` filter or an optional `parent_plan_id` filter to trace scenario lineage.

Within a `DRAFT` plan the cartographer lays down districts. Creating a district requires a `district_number` — its ordinal, at least 1 and unique within the plan; a duplicate is rejected with `ERR_DUPLICATE_DISTRICT_NUMBER`. A district may also carry an optional `name`, an `is_contiguous` flag asserting that its blocks form a geometrically connected shape (defaulting to true), an `incumbent_name` for the sitting officeholder, and an `incumbent_home_geoid` giving the GEOID of the block containing that incumbent's residence. A district begins with `assigned_population` of 0, its deviation computed against the ideal.

Population is placed into districts one block at a time through **block assignments**. Assigning a block requires the `district_id` receiving it, the `census_block_id` being placed, and the `expected_plan_version` for concurrency control (§2.7). The district must belong to the plan named in the path (`ERR_DISTRICT_PLAN_MISMATCH`), and the block must belong to the plan's jurisdiction (`ERR_BLOCK_JURISDICTION_MISMATCH`). Block assignments may only be created while the parent plan is in `DRAFT` or `UNDER_REVIEW`; in any other status the attempt is `ERR_INVALID_STATE`. Each assignment records its `plan_id` and starts `ACTIVE`. Because at most one active assignment may exist per plan-and-block pair, assigning a block that already has an active assignment in the plan moves the prior assignment to `SUPERSEDED` rather than creating a duplicate. A successful create recomputes the affected districts' `assigned_population`, deviation, and minority metrics, recomputes the plan's deviation and VRA metrics and `is_compliant`, and increments the plan's `version` by 1.

A `Cartographer` may pull a block back out by removing its assignment, but only while the plan is in `DRAFT` or `UNDER_REVIEW` (otherwise `ERR_INVALID_STATE`). Removal moves the assignment to `REMOVED` and recomputes the district and plan metrics as a compensating adjustment. Block assignments can be read individually or listed with optional `plan_id`, `district_id`, or `census_block_id` filters.

Each district's population figures are always reconciled from its currently active assignments. Its `assigned_population` is the sum of `population` over the census blocks reached through the district's `ACTIVE` block assignments; superseded and removed assignments are excluded. Its `target_population` is the parent jurisdiction's `ideal_district_population` at read time. Its `deviation` is the assigned population minus the target, rounded to the nearest whole number. Its `deviation_pct` is that same difference divided by the target and multiplied by 100, rounded to 2 decimal places — and defined as 0.00 whenever the target population is 0 (avoiding division by zero). A district holding no blocks still reports a deviation computed against the target.

### 3.3. Voting-Rights Metrics and the Geography Report

Alongside population, each district carries voting-rights arithmetic. Its `minority_vap_pct` is the sum of `minority_vap` divided by the sum of `voting_age_population`, taken over the district's active block assignments, multiplied by 100 and rounded to 2 decimal places; when the voting-age sum is 0 the percentage is 0.00. A district is flagged `is_majority_minority` when its `minority_vap_pct` is **strictly greater than 50.0** — a district sitting at exactly 50.00 is not majority-minority.

The district list doubles as a geography report and surfaces incumbency. A district's `incumbent_retained` flag is true precisely when the census block whose `geoid` equals the district's `incumbent_home_geoid` currently has an `ACTIVE` block assignment to that district; when `incumbent_home_geoid` is null, `incumbent_retained` is false. This lets a mapmaker see at a glance whether a boundary change has drawn an incumbent out of the district they represent.

At the plan level, deviation is summarized under both standards described in §2.6, and the summarization order is pinned: **each district's `deviation_pct` is rounded to 2 decimal places first, and only then are the maximum, minimum, and range taken over those already-rounded values.** The plan's `max_abs_deviation_pct` is the maximum of the absolute values of the districts' rounded deviation percentages; its `overall_deviation_range_pct` is the maximum rounded deviation percentage minus the minimum. A plan with no districts reports 0.00 for both. The plan's `majority_minority_district_count` is the number of its districts flagged `is_majority_minority`.

A plan's overall `is_compliant` gate is true only when all four of the following hold together: the `max_abs_deviation_pct` is at most 5.00% (the boundary is inclusive — exactly 5.00% still passes); the `majority_minority_district_count` is at least the jurisdiction's `required_majority_minority_districts`; every district in the plan has `is_contiguous` true; and the plan forms a complete partition, meaning every census block in the jurisdiction has exactly one `ACTIVE` block assignment in the plan. If any of the four fails, the plan is not compliant.

A `Demographer` can snapshot compliance at any time by running a compliance check of a chosen `check_type` — `POPULATION_DEVIATION`, `VRA_MINORITY`, or `CONTIGUITY`. The check computes a `result_status` from the plan's live metrics and freezes copies of `max_abs_deviation_pct`, `overall_deviation_range_pct`, and `majority_minority_district_count`, together with a human-readable `detail`, onto the immutable record (which carries `plan_id` and, as noted in §2.4, only `id` and `created_at`). The `result_status` is computed as follows:

- For `POPULATION_DEVIATION`: `PASS` when the plan's `max_abs_deviation_pct` is at most 5.0; `WARN` when it is above 5.0 but at most 10.0; `FAIL` when it exceeds 10.0.
- For `VRA_MINORITY`: `FAIL` when the plan's `majority_minority_district_count` is below the jurisdiction's `required_majority_minority_districts`; otherwise `WARN` when at least one district is an opportunity-but-not-majority district — that is, a district whose `minority_vap_pct` is greater than 45.0 and at most 50.0; otherwise `PASS`.
- For `CONTIGUITY`: `PASS` when every district in the plan is contiguous, `FAIL` otherwise.

Compliance checks for a plan can be listed in creation order.

### 3.4. Public Comment and Hearings

Once a plan has been submitted for review (§3.5), the commission can invite the public in. Opening the comment period moves the plan from `UNDER_REVIEW` to `COMMENT_OPEN` and stamps `comment_opened_at` with the current logical-clock instant. This step is gated on demographics: the plan's most recent `POPULATION_DEVIATION` compliance check must exist and must not have a `result_status` of `FAIL`; if there is no such check or the latest one failed, the request is rejected with `ERR_DEVIATION_CHECK_FAILED`.

While comment is open, a `PublicParticipant` submits a comment on the plan by providing a `commenter_name` and the `comment_text`. Each comment records its `plan_id` and starts with a `disposition` of `PENDING`. A `CommissionChair` later resolves each comment by dispositioning it to one of three terminal values — `ACKNOWLEDGED`, `INCORPORATED`, or `DISMISSED` — supplied as the `disposition` field. A plan's comments can be listed in order.

Public hearings are held at civic venues. An `ElectionClerk` creates a `Venue` under a jurisdiction with a `name` and a seated `capacity` (at least 1); venues can be read singly or listed by jurisdiction. A `CommissionChair` schedules a hearing on a plan by naming the `venue_id` and giving the `scheduled_start` and `scheduled_end` as ISO 8601 UTC instants; the end must be strictly after the start, or the request is `ERR_INVALID_DATE_RANGE`. The hearing records its `plan_id`, starts in `SCHEDULED`, and the venue must belong to the plan's jurisdiction (`ERR_VENUE_JURISDICTION_MISMATCH`). A hearing may only be scheduled while the plan is in `COMMENT_OPEN` or `HEARING_SCHEDULED`; otherwise `ERR_INVALID_STATE`. Scheduling the first hearing on a `COMMENT_OPEN` plan advances it to `HEARING_SCHEDULED`; scheduling additional hearings on an already-`HEARING_SCHEDULED` plan leaves the status unchanged.

Venue time is protected against double-booking under **buffered half-open** semantics with a 60-minute setup-and-teardown buffer between events. A new hearing occupies the interval from its start up to but not including its end, and each existing `SCHEDULED` hearing at the same venue reserves its own interval plus a one-hour tail. Concretely, the new hearing conflicts with an existing one at the same venue when the new hearing's start falls before the existing hearing's end plus 60 minutes **and** the existing hearing's start falls before the new hearing's end plus 60 minutes; such a collision is rejected with `ERR_VENUE_TIME_CONFLICT`. Back-to-back hearings are permitted only when at least 60 minutes separate the end of one from the start of the next. This overlap check considers `SCHEDULED` hearings at the same venue regardless of which plan they belong to.

A `CommissionChair` marks a hearing `HELD` once the logical clock has reached its `scheduled_start`; an attempt before that instant is rejected with `ERR_HEARING_NOT_STARTED`, and a hold on a hearing that is not `SCHEDULED` is `ERR_INVALID_STATE`. A held hearing is what later unlocks adoption. A hearing may instead be cancelled, moving it to `CANCELLED`; if its plan was in `HEARING_SCHEDULED` and this was the last remaining `SCHEDULED` hearing on the plan, the plan reverts to `COMMENT_OPEN`. Hearings can be read singly or listed by `plan_id` or `venue_id`.

### 3.5. The Plan Lifecycle: Review, Revision, Rejection, and Adoption

A plan travels a defined path, and several of its transitions carry cascading consequences. A `Cartographer` submits a `DRAFT` plan for review, moving it to `UNDER_REVIEW`. Submission requires that the plan have at least one district and that it form a complete partition — every census block in the jurisdiction assigned to exactly one active block assignment in the plan; a plan with unassigned or multiply-assigned blocks is rejected with `ERR_INCOMPLETE_PARTITION`. Submission recomputes the plan's deviation and VRA metrics.

From `UNDER_REVIEW`, the commission can open comment (§3.4) or reject the plan outright. A `CommissionChair` rejects a plan by moving it to the terminal `REJECTED` state; rejection cascades by dismissing every `PENDING` public comment on the plan (each moves to `DISMISSED`) and cancelling every `SCHEDULED` hearing on the plan (each moves to `CANCELLED`).

The process is deliberately cyclic. From `HEARING_SCHEDULED`, a `Demographer` may request a revision, which sends the plan back to `UNDER_REVIEW` for further editing and re-review and cancels every `SCHEDULED` hearing on the plan. From `UNDER_REVIEW` the plan can then be re-opened for comment and re-scheduled for hearings, looping as many times as the process demands.

Adoption is the culmination and the most heavily guarded transition. A `CommissionChair` adopts a plan that is in `HEARING_SCHEDULED`, and every one of the following must hold: at least one hearing on the plan is in status `HELD`, or the request is rejected with `ERR_NO_HELD_HEARING`; the plan's `is_compliant` gate is true, or the request is rejected with `ERR_PLAN_NOT_COMPLIANT`; and the adopting `X-User-ID` differs from the plan's `created_by_user_id`, or the request is rejected with `ERR_SEGREGATION_OF_DUTIES`. On success the plan moves to `ADOPTED`, its `adopted_at` is stamped with the current logical-clock instant, every other non-terminal plan in the same jurisdiction is superseded — each such plan moves to `SUPERSEDED`, and that supersession itself dismisses those plans' `PENDING` comments and cancels their `SCHEDULED` hearings — and a GIS export of the adopted plan is generated automatically in `COMPLETE` status with an `export_format` of `GEOJSON` (§3.8).

### 3.6. Precincts: Creation, Split, Merge, Retire, and Certify

Precincts are the operational containers that group census blocks for election administration, and they evolve independently of redistricting plans. An `ElectionClerk` creates a precinct under a jurisdiction with a `name` and an optional list of `census_block_ids` to place in it; each named block has its `precinct_id` set to the new precinct. A new precinct starts `ACTIVE` with a `voter_count_basis` of `PROVISIONAL` and no split lineage (`parent_precinct_id` null). Precincts can be listed by `jurisdiction_id` or by `parent_precinct_id` (to find a precinct's split children), and read individually to see the current `version` and computed `registered_voters`.

A precinct's `registered_voters` is computed from the census blocks currently pointing at it — those whose `precinct_id` equals the precinct's id — and comes in **two variants** driven by `voter_count_basis`. Under the `PROVISIONAL` basis the count is an estimate: the sum of `voting_age_population` over the precinct's blocks multiplied by a registration rate of 0.85, rounded to the nearest whole number — a precinct holding 1,000 VAP estimates 850 voters. Under the `CERTIFIED` basis the count is the sum of the blocks' actual `registered_voters` — the same precinct might certify, say, 812, a different number from the same blocks. Whenever a precinct's status becomes `SPLIT` or `MERGED`, its `registered_voters` is forced to 0.

An `ElectionClerk` can restructure precincts three ways:

- **Split.** An `ACTIVE` precinct is split into two children by supplying `child_a_name` with the geoids `child_a_block_geoids` for the first child and `child_b_name` with `child_b_block_geoids` for the second. The precinct must currently hold at least 2 active census blocks — a precinct with fewer cannot be split (`ERR_VALIDATION`) — and the two geoid groups must exactly partition the precinct's current blocks: every block appears in exactly one group and no foreign block is named, or the request is rejected with `ERR_INCOMPLETE_PARTITION`. On success the system creates child precinct A and child precinct B, each with `parent_precinct_id` set to the original; reassigns each census block's `precinct_id` to its child; recomputes both children's `registered_voters` from their newly assigned blocks; and moves the original precinct to `SPLIT` with its `registered_voters` set to 0.

- **Merge.** An `ACTIVE` precinct is merged into a `target_precinct_id`. The target must exist, be `ACTIVE` (otherwise `ERR_INVALID_STATE`), be in the same jurisdiction (otherwise `ERR_PRECINCT_JURISDICTION_MISMATCH`), and not be the precinct itself (otherwise `ERR_VALIDATION`). On success every census block's `precinct_id` moves from this precinct to the target, the target's `registered_voters` is recomputed, and this precinct moves to `MERGED` with its `registered_voters` set to 0.

- **Retire.** An `ACTIVE` precinct with no active census blocks and no active polling assignment is retired, moving to `RETIRED`. If it still holds blocks or still has an active polling assignment, the request is rejected with `ERR_PRECINCT_NOT_EMPTY`.

Finally, an `ElectionClerk` can **certify** an `ACTIVE` precinct, switching its `voter_count_basis` to `CERTIFIED` and recomputing `registered_voters` from the actual rolls under the certified variant above.

### 3.7. Polling Places and Early-Voting Assignments

An `ElectionClerk` creates a `PollingPlace` under a jurisdiction with a `name`, a street `address`, and a `capacity` (the maximum registered voters it can serve on election day, at least 1). It starts `ACTIVE` with `assigned_registered_voters` of 0. Polling places can be read singly — exposing computed utilization — or listed by jurisdiction.

Precincts are assigned to polling places for early-voting windows. Creating a polling assignment names the `polling_place_id`, the inclusive early-voting window `ev_start_date` and `ev_end_date` (dates in `YYYY-MM-DD` form, with the end on or after the start, or `ERR_INVALID_DATE_RANGE`), and the `expected_precinct_version` for concurrency control (§2.7). The assignment records its `precinct_id` and starts `ACTIVE`. The referenced polling place must be `ACTIVE`, or the request is `ERR_INVALID_STATE`. Creating a new assignment for a precinct supersedes that precinct's prior `ACTIVE` polling assignment (moving it to `SUPERSEDED`), recomputes the `assigned_registered_voters` on both the old and the new polling place, and increments the precinct's `version` by 1.

Two constraints protect a polling place. First, an early-voting **window conflict**: a polling place cannot host two overlapping early-voting windows for different precincts. Under closed-interval semantics — both endpoints inclusive — the new window conflicts with an existing `ACTIVE` assignment at the same polling place belonging to a **different** precinct when the new window's start date is on or before the existing window's end date **and** the existing window's start date is on or before the new window's end date; even a single shared date counts as a conflict. A collision is rejected with `ERR_EV_WINDOW_CONFLICT`. Second, a **capacity** constraint: a polling place's `assigned_registered_voters` is the sum of `registered_voters` over the precincts with an `ACTIVE` polling assignment to it, and assigning a precinct must not push that total strictly above the place's `capacity`; an assignment that would exceed capacity is rejected with `ERR_POLLING_CAPACITY_EXCEEDED`. A polling place's `utilization_pct` is its `assigned_registered_voters` divided by `capacity` times 100, rounded to 2 decimal places, and its `is_over_capacity` flag is true only when `assigned_registered_voters` is strictly greater than `capacity` — sitting exactly at capacity is not over.

A polling place may be closed once it has no active polling assignment, moving it to `CLOSED`; closing one that still has an active assignment is rejected with `ERR_POLLING_PLACE_IN_USE`. Polling assignments can be read singly or listed by `precinct_id` or `polling_place_id`.

### 3.8. Scenario Comparison and GIS Export

Because a jurisdiction may carry several competing plans at once, the system supports side-by-side comparison. Given a plan and an `other_plan_id` (supplied as a query parameter, required — its absence is rejected with `ERR_VALIDATION`, and an unknown value with `ERR_PLAN_NOT_FOUND`), the comparison reports the differences between the two plans' summary metrics: `max_abs_deviation_pct_delta`, `overall_deviation_range_pct_delta`, and `majority_minority_district_count_delta`, each computed as this plan's metric minus the other plan's metric, so a commissioner can judge which scenario balances population and protects minority representation better. The comparison response also echoes `plan_id` and `other_plan_id` alongside the three delta fields.

When a plan is finalized, its geometry is exported for the downstream mapping systems. An `ElectionClerk` creates a GIS export of a plan by naming an `export_format` — `GEOJSON` or `SHAPEFILE`. An export is also produced automatically when a plan is adopted. The export records its `plan_id` and computes three figures: `block_count`, the number of `ACTIVE` block assignments in the plan at export time; `district_count`, the number of districts in the plan; and a `checksum`, a deterministic lowercase hexadecimal SHA-256 digest. The checksum is formed by taking, for every `ACTIVE` block assignment, the pair of its district's `district_number` and its census block's `geoid`; sorting those pairs by `district_number` ascending and then by `geoid` ascending (never by id or in any random order); rendering each pair as its district number, a colon, and its geoid; joining the rendered pairs with a vertical-bar separator; and hashing the resulting string. An export's `status` is `COMPLETE` when the plan is `ADOPTED` and `FAILED` otherwise. A plan's exports can be listed.

## 4. Endpoint Definitions

New-resource creations return HTTP 201; state transitions, other modifications, and reads return HTTP 200. All request and response bodies use the envelope of §2.2; the full set of body fields and side effects for each operation is described in the §3 narrative rather than repeated here.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/_clock/set_current_utc` | Set the server logical clock | Cartographer, Demographer, CommissionChair, ElectionClerk |
| POST | `/jurisdictions` | Create a jurisdiction | Cartographer |
| GET | `/jurisdictions/{jurisdictionId}` | Read a jurisdiction incl. computed totals | Cartographer, Demographer, CommissionChair, ElectionClerk, PublicParticipant |
| POST | `/jurisdictions/{jurisdictionId}/census-blocks` | Add a census block | Cartographer |
| GET | `/census-blocks/{censusBlockId}` | Read a single census block | Cartographer, Demographer, CommissionChair, ElectionClerk, PublicParticipant |
| GET | `/census-blocks` | List census blocks (filter by jurisdiction or precinct) | Cartographer, Demographer, CommissionChair, ElectionClerk, PublicParticipant |
| POST | `/jurisdictions/{jurisdictionId}/precincts` | Create a precinct and place blocks in it | ElectionClerk |
| GET | `/precincts` | List precincts (filter by jurisdiction or split-parent) | Cartographer, Demographer, CommissionChair, ElectionClerk, PublicParticipant |
| GET | `/precincts/{precinctId}` | Read a single precinct | Cartographer, Demographer, CommissionChair, ElectionClerk, PublicParticipant |
| POST | `/precincts/{precinctId}/split` | Split an ACTIVE precinct into two children | ElectionClerk |
| POST | `/precincts/{precinctId}/merge` | Merge a precinct into a target precinct | ElectionClerk |
| POST | `/precincts/{precinctId}/retire` | Retire an empty ACTIVE precinct | ElectionClerk |
| POST | `/precincts/{precinctId}/certify` | Switch a precinct's voter basis to CERTIFIED | ElectionClerk |
| POST | `/jurisdictions/{jurisdictionId}/venues` | Create a hearing venue | ElectionClerk |
| GET | `/venues/{venueId}` | Read a single venue | Cartographer, Demographer, CommissionChair, ElectionClerk, PublicParticipant |
| GET | `/venues` | List venues (filter by jurisdiction) | Cartographer, Demographer, CommissionChair, ElectionClerk, PublicParticipant |
| POST | `/jurisdictions/{jurisdictionId}/polling-places` | Create a polling place | ElectionClerk |
| GET | `/polling-places/{pollingPlaceId}` | Read a single polling place | Cartographer, Demographer, CommissionChair, ElectionClerk, PublicParticipant |
| GET | `/polling-places` | List polling places (filter by jurisdiction) | Cartographer, Demographer, CommissionChair, ElectionClerk, PublicParticipant |
| POST | `/polling-places/{pollingPlaceId}/close` | Close a polling place | ElectionClerk |
| POST | `/precincts/{precinctId}/polling-assignments` | Assign a precinct to a polling place (OCC on precinct) | ElectionClerk |
| GET | `/polling-assignments/{pollingAssignmentId}` | Read a single polling assignment | Cartographer, Demographer, CommissionChair, ElectionClerk, PublicParticipant |
| GET | `/polling-assignments` | List polling assignments (filter by precinct or polling place) | Cartographer, Demographer, CommissionChair, ElectionClerk, PublicParticipant |
| POST | `/jurisdictions/{jurisdictionId}/plans` | Create a plan (fork with parent_plan_id) | Cartographer |
| GET | `/plans` | List plans (filter by jurisdiction or fork-parent) | Cartographer, Demographer, CommissionChair, ElectionClerk, PublicParticipant |
| GET | `/plans/{id}` | Read a plan incl. computed metrics | Cartographer, Demographer, CommissionChair, ElectionClerk, PublicParticipant |
| GET | `/plans/{id}/comparison` | Scenario compare against other_plan_id | Cartographer, Demographer, CommissionChair, ElectionClerk, PublicParticipant |
| POST | `/plans/{id}/districts` | Create a district in a DRAFT plan | Cartographer |
| GET | `/plans/{id}/districts` | List a plan's districts (geography report) | Cartographer, Demographer, CommissionChair, ElectionClerk, PublicParticipant |
| POST | `/plans/{id}/block-assignments` | Assign a census block to a district (OCC on plan) | Cartographer |
| GET | `/block-assignments/{blockAssignmentId}` | Read a single block assignment | Cartographer, Demographer, CommissionChair, ElectionClerk, PublicParticipant |
| GET | `/block-assignments` | List block assignments (filter by plan, district, or block) | Cartographer, Demographer, CommissionChair, ElectionClerk, PublicParticipant |
| POST | `/block-assignments/{blockAssignmentId}/remove` | Remove an ACTIVE block assignment | Cartographer |
| POST | `/plans/{id}/compliance-checks` | Run a compliance check | Demographer |
| GET | `/plans/{id}/compliance-checks` | List compliance-check snapshots | Cartographer, Demographer, CommissionChair, ElectionClerk, PublicParticipant |
| POST | `/plans/{id}/submit-review` | Submit a DRAFT plan for review | Cartographer |
| POST | `/plans/{id}/open-comment` | Open the public-comment period | CommissionChair |
| POST | `/plans/{id}/request-revision` | Send a hearing-stage plan back for revision | Demographer |
| POST | `/plans/{id}/reject` | Reject an UNDER_REVIEW plan | CommissionChair |
| POST | `/plans/{id}/adopt` | Adopt a compliant plan (four-eyes SoD) | CommissionChair |
| POST | `/plans/{id}/hearings` | Schedule a public hearing | CommissionChair |
| GET | `/hearings/{hearingId}` | Read a single hearing | Cartographer, Demographer, CommissionChair, ElectionClerk, PublicParticipant |
| GET | `/hearings` | List hearings (filter by plan or venue) | Cartographer, Demographer, CommissionChair, ElectionClerk, PublicParticipant |
| POST | `/hearings/{hearingId}/hold` | Mark a scheduled hearing as HELD | CommissionChair |
| POST | `/hearings/{hearingId}/cancel` | Cancel a scheduled hearing | CommissionChair |
| POST | `/plans/{id}/comments` | Submit a public comment | PublicParticipant |
| GET | `/plans/{id}/comments` | List a plan's public comments | Cartographer, Demographer, CommissionChair, ElectionClerk, PublicParticipant |
| POST | `/comments/{commentId}/disposition` | Disposition a PENDING comment | CommissionChair |
| POST | `/plans/{id}/exports` | Create a GIS export of the plan | ElectionClerk |
| GET | `/plans/{id}/exports` | List a plan's GIS exports | Cartographer, Demographer, CommissionChair, ElectionClerk, PublicParticipant |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_UNAUTHORIZED | 403 |
| ERR_JURISDICTION_NOT_FOUND | 404 |
| ERR_PLAN_NOT_FOUND | 404 |
| ERR_DISTRICT_NOT_FOUND | 404 |
| ERR_CENSUS_BLOCK_NOT_FOUND | 404 |
| ERR_PRECINCT_NOT_FOUND | 404 |
| ERR_POLLING_PLACE_NOT_FOUND | 404 |
| ERR_POLLING_ASSIGNMENT_NOT_FOUND | 404 |
| ERR_HEARING_NOT_FOUND | 404 |
| ERR_COMMENT_NOT_FOUND | 404 |
| ERR_BLOCK_ASSIGNMENT_NOT_FOUND | 404 |
| ERR_EXPORT_NOT_FOUND | 404 |
| ERR_INVALID_STATE | 409 |
| ERR_DISTRICT_PLAN_MISMATCH | 422 |
| ERR_BLOCK_JURISDICTION_MISMATCH | 422 |
| ERR_PRECINCT_JURISDICTION_MISMATCH | 422 |
| ERR_VENUE_JURISDICTION_MISMATCH | 422 |
| ERR_DUPLICATE_DISTRICT_NUMBER | 409 |
| ERR_DUPLICATE_GEOID | 409 |
| ERR_INCOMPLETE_PARTITION | 409 |
| ERR_VENUE_TIME_CONFLICT | 409 |
| ERR_EV_WINDOW_CONFLICT | 409 |
| ERR_POLLING_CAPACITY_EXCEEDED | 409 |
| ERR_PRECINCT_NOT_EMPTY | 409 |
| ERR_POLLING_PLACE_IN_USE | 409 |
| ERR_HEARING_NOT_STARTED | 409 |
| ERR_DEVIATION_CHECK_FAILED | 422 |
| ERR_NO_HELD_HEARING | 422 |
| ERR_SEGREGATION_OF_DUTIES | 403 |
| ERR_PLAN_NOT_COMPLIANT | 422 |
| ERR_VALIDATION | 422 |
| ERR_INVALID_DATE_RANGE | 422 |
| ERR_STALE_PLAN_VERSION | 412 |
| ERR_STALE_PRECINCT_VERSION | 412 |
