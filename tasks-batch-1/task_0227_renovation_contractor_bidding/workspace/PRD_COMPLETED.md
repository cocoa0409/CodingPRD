# Renovation Contractor Bidding API — Product Requirements Document

## 1. Introduction

Home renovation projects routinely stall at the seams between the parties who must cooperate to complete them: the homeowner who defines the work and holds the budget, the contractors who compete to win it, the escrow agent who guards the money, and the platform that vouches for who is allowed to bid in the first place. This API exists to make that multi-party negotiation auditable and safe. It carries a project from a private draft, through an open competitive bidding window, to the award of a single winning bid, and onward through a milestone-driven payment schedule in which money is deposited into escrow, drawn down in sequence, and released only against signed lien waivers.

The system rests on two intertwined disciplines. The first is the negotiation discipline — qualifying contractors, ranking competing bids on price, schedule, and reputation, and awarding work under optimistic-concurrency protection so two homeowners' views of the same project never collide. The second is the ledger discipline — every cent funded into escrow is tracked as it moves between available, retained, and released balances, and the API guarantees that the escrow can never be over-drawn. Change orders adjust the contract value mid-flight, retainage is held back on each draw and released only at the end, and disputes can freeze a project and rewind a draw. Throughout, the contract value, the escrow balances, and the milestone schedule are kept mutually consistent so that no party can be paid for work that was never funded, and no contractor can be denied retainage that was legitimately earned.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelopes, and cross-cutting principles that govern every endpoint.

### 2.1. User and Role-Based Access Control

Every request other than the two public registration calls must be authenticated through two mandatory HTTP headers: `X-User-ID`, which identifies the acting principal, and `X-User-Role`, which declares the principal's operational capacity. The system recognizes exactly five roles: `Homeowner`, `Contractor`, `EscrowAgent`, `PlatformAdmin`, and `Anonymous`. A request that omits either header, or that carries an `X-User-Role` that is not one of these recognized values, is rejected with `ERR_UNAUTHENTICATED`. A request whose role is recognized and authenticated but is not permitted to perform the requested operation under the access matrix in Section 4 is rejected with `ERR_FORBIDDEN`.

Two of the roles are **entity-backed**, meaning their `X-User-ID` is the identity of a persisted record. When `X-User-Role` is `Homeowner`, `X-User-ID` is the `id` of the acting `Homeowner`; any ownership check on a resource that references a homeowner compares that resource's `homeowner_id` to `X-User-ID`. When `X-User-Role` is `Contractor`, `X-User-ID` is the `id` of the acting `Contractor`; ownership checks on a resource that references a contractor compare that resource's `contractor_id` to `X-User-ID`. The remaining three roles are **opaque**: when `X-User-Role` is `EscrowAgent`, `PlatformAdmin`, or `Anonymous`, the `X-User-ID` is an operator identifier not tied to any persisted entity, and the server does not compare it to any record's `id`. For the operations that require ownership — a homeowner acting on their own project and its sub-resources, and a contractor acting on their own bids and draw requests — a caller who is authenticated and role-permitted but is not the owner of the targeted resource is rejected with `ERR_NOT_RESOURCE_OWNER`. Ownership is enforced only on operations that mutate a resource (writes and state transitions); read endpoints (the GET operations) perform no ownership check, so any authenticated, role-permitted caller may fetch or list any resource regardless of who owns it.

The `Anonymous` role exists solely to expose the registration surface. Homeowner registration and contractor registration are the only two operations that do not require authentication headers.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every resource in the system carries a server-minted `id`, formatted as a UUID with no type prefix. Every resource also carries a `created_at` timestamp, an ISO 8601 UTC timestamp with three fractional digits, recorded when the resource is first created. List endpoints return resources ordered by this `created_at` value ascending.

Resources in this domain are all mutable and therefore additionally carry an `updated_at` timestamp and an integer `version`. The `updated_at` field is refreshed on every mutation, and `version` begins at its initial value of `1` at creation and increments by one on every mutation of the resource. The `version` field underpins the optimistic-concurrency mechanism described in Section 2.9 and is the value clients echo back to prove they are acting on a current view. Whenever a server-driven cascade mutates a resource — for example, when awarding a project rejects competing bids, or when resolving a dispute rewinds a draw — that mutation likewise refreshes the affected resource's `updated_at` and increments its `version`, exactly as a directly requested change would.

### 2.5. Monetary Values, Quantities, and Rounding

All monetary amounts in this system are expressed as integer counts of cents; there are no fractional cents and no floating monetary fields. Several amounts are derived by multiplying a quantity (which may be fractional) by a per-unit price in cents. Wherever such a product is computed, the result is rounded to a whole number of cents using the round-half-up convention — a value whose fractional part is exactly one half is rounded up to the next whole cent.

A critical and load-bearing rule governs aggregation of these line-level amounts: **rounding is applied per line before summing, never after.** When a bid's total or a project's estimate is assembled from many priced lines, each line's amount is rounded to whole cents first, and only then are the rounded line amounts added together. The two reputation-related rounding rules differ in their decimal places: a contractor's average rating is rounded half-up to two decimal places, while the weighted bid rank score is rounded half-up to four decimal places. Each of these is stated in full in its workflow narrative in Section 3.

### 2.6. Escrow Ledger Integrity

Each awarded project is backed by exactly one escrow account, and that account is the single source of truth for the money in motion. The escrow tracks four derived amounts in cents: `funded_cents`, the total the homeowner has deposited; `released_cents`, the total paid out to the contractor across milestones that have been paid; `retained_cents`, the cumulative retainage held back across approved draws and not yet released; and `available_cents`, which is always equal to `funded_cents` minus `released_cents` minus `retained_cents`. The available balance is an exact integer computation — no rounding is involved — and it carries a hard invariant: it must never become negative. Any transition that would drive the available balance below zero is rejected before any mutation occurs, so the ledger is never left in an inconsistent state. Each escrow also carries a `status` lifecycle that begins at `UNFUNDED` and moves through `FUNDED` to `CLOSED`, and the escrow record references the project it backs through its `project_id`.

### 2.7. Sequential Milestone Schedule

A project's payment schedule is a set of milestones, each occupying a distinct ordinal position. Money is drawn down strictly in order: a draw may only be requested for the lowest-positioned milestone that has not yet entered the draw pipeline. This sequencing, the uniqueness of milestone positions, and the requirement that the release percentages cover the whole contract are detailed in the milestone and draw narratives of Section 3, where they sit beside the workflows they constrain.

### 2.8. Nested Resource Retrieval and Existence Checks

Several read endpoints address a resource through a path that contains a parent identifier followed by a sub-collection — for example, retrieving the scope line items of a project, or the bid line items that price a particular scope line. For any such request, the server validates the identifiers left to right and rejects the request with `ERR_NOT_FOUND` at the first identifier in the path that does not correspond to an existing resource. More generally, for any endpoint, every resource referenced either by a path identifier or by a foreign-key field in the request body must exist; if any referenced resource is absent, the request is rejected with `ERR_NOT_FOUND`. This existence sweep is performed left to right and before the business preconditions of the operation are evaluated.

### 2.9. Optimistic Concurrency Control

Two write operations in this system are guarded against acting on a stale view of a parent record. In each case the client must supply, as a non-optional field of the request body, the version of the parent it last observed; if that version does not match the parent's current `version`, the write is rejected and nothing is mutated.

The first guarded operation is awarding a bid on a project. The award request must carry `expected_project_version`, and the value must equal the target project's current `version`. If a prior award (or any other mutation) has already advanced the project's version since the client last read it, the client's view is stale — the project may already have left its open-for-bids state — and the award is rejected with `ERR_STALE_PROJECT_VERSION` (HTTP 412). The second guarded operation is approving a change order. The approval request must carry `expected_bid_version`, and the value must equal the awarded bid's current `version`. Because each approved change order adjusts the contract value and advances the awarded bid's version, a second approval still carrying the older version is stale and is rejected with `ERR_STALE_BID_VERSION` (HTTP 412). No other endpoint accepts or requires a version field; operations not named here perform no optimistic-concurrency check.

### 2.10. The Logical Clock

Time-sensitive rules in this system — most importantly the bidding window — are evaluated against a server-controlled logical clock rather than wall-clock time, so that the bid deadline can be exercised deterministically. A platform-administrative capability sets the server's current UTC instant to a supplied `to_iso8601` value and echoes back the new clock as `current_utc`; all comparisons against a project's bid deadline and against a contractor's license expiry use this current clock.

## 3. Business Logic & Workflows

### 3.1. Onboarding and Qualifying Contractors

A contractor joins the platform through the public registration surface by supplying a business `legal_name`, a primary `trade`, a state `license_number`, a `license_expiry` instant, and a liability `insurance_coverage_cents` figure. The `trade` must be one of `GENERAL`, `ELECTRICAL`, `PLUMBING`, `HVAC`, or `ROOFING`, and the insurance figure must be zero or greater. A newly registered contractor begins with a `qualification_status` of `PENDING` and is not yet allowed to bid.

A `PlatformAdmin` reviews and qualifies contractors. Qualifying a contractor advances `qualification_status` from `PENDING` to `QUALIFIED`, but only when three conditions hold: the `license_number` is non-empty, the `license_expiry` is in the future relative to the current clock, and the `insurance_coverage_cents` is at least 1,000,000 cents — that is, at least ten thousand dollars of coverage. The same admin capability re-qualifies a contractor who has been suspended, moving `qualification_status` from `SUSPENDED` back to `QUALIFIED`; re-qualification still requires that the `license_expiry` be in the future and the `insurance_coverage_cents` be at least ten thousand dollars (the non-empty-license check is not re-imposed on re-qualification). An admin may suspend a qualified contractor, moving `qualification_status` from `QUALIFIED` to `SUSPENDED` with no further precondition, and may revoke a suspended contractor, moving `qualification_status` from `SUSPENDED` to the terminal `REVOKED` state, again with no further precondition. Every failed precondition across these qualification transitions — attempting a transition from a source state that does not permit it (for example, qualifying a contractor that is neither `PENDING` nor `SUSPENDED`, suspending one that is not `QUALIFIED`, or revoking one that is not `SUSPENDED`), an empty `license_number` on a `PENDING → QUALIFIED` qualification, a `license_expiry` that is not in the future, or `insurance_coverage_cents` below the minimum — is rejected with `ERR_INVALID_STATE`. A contractor's standing also accumulates a reputation: `rating_sum` holds the running total of the star ratings the contractor has received, `rating_count` holds how many ratings have been received, and `average_rating` is the derived reputation score described in Section 3.8.

### 3.2. Drafting a Project: Scope and Milestones

A `Homeowner` registers by supplying a `full_name` and an `email`; the email must be unique across all homeowners, and a registration whose email duplicates an existing homeowner's is rejected with `ERR_INVALID_REQUEST`. A homeowner then creates a project by supplying the owning `homeowner_id`, a `title`, a `budget_cap_cents` ceiling that must be strictly greater than zero, a `bid_deadline`, and a `required_trade` that the eventual winner must hold. An optional `min_rating` floor may be supplied; it defaults to zero (meaning no rating floor), and when supplied must be between zero and five inclusive. A new project starts in `DRAFT` status with a `contract_value_cents` of zero, an `awarded_bid_id` of null, and `scope_locked` set to false.

While the project is in `DRAFT`, the homeowner builds out its scope and its payment schedule. Each scope line is added by supplying a `description`, a `quantity` greater than zero, a `unit` of measure that must be one of `SQFT`, `UNIT`, `HOUR`, or `LUMP`, and an `estimated_unit_cost_cents` that must be zero or greater. Each scope line references its project through `project_id`, and the server computes that line's `estimated_total_cents` as the line's `quantity` multiplied by its `estimated_unit_cost_cents`, rounded half-up to whole cents. Once a bid has been awarded the project's `scope_locked` flag is true, and any further attempt to add a scope line is refused — scope is frozen at award time.

The payment schedule is built from milestones. Each milestone is added with a `sequence` ordinal that must be at least one and unique within the project, a `title`, and a `release_pct` expressed as a fraction of the contract value — for instance, 0.30 represents thirty percent — which must be greater than zero and at most one. Each milestone references its project through `project_id` and begins in `PENDING` status. If a homeowner tries to add a milestone whose `sequence` ordinal is already occupied by an existing milestone on that project, the request is rejected with `ERR_MILESTONE_SEQUENCE_TAKEN`. The homeowner may at any time request a computed estimate of the project, which returns a `data` object holding the sum of every scope line's `estimated_total_cents` in a field named `estimated_total_cents` — each line rounded to whole cents first and then added together, in the same pinned per-line-then-sum order used for bids — together with the count of lines contributing to it as `line_count`. This estimate read performs no ownership check, so any role-permitted caller (`Homeowner` or `PlatformAdmin`) may request it.

### 3.3. Opening for Bids and the Bidding Window

Opening a project moves its `status` from `DRAFT` to `OPEN_FOR_BIDS` and exposes it to contractors. The homeowner may open the project only when all of the following hold: at least one scope line item exists, at least one milestone exists, the sum of all the project's milestone `release_pct` values equals exactly 1.0, and the current clock is before the project's `bid_deadline`. If the milestone percentages do not sum to exactly one, the open is rejected with `ERR_MILESTONE_PCT_INVALID`.

A contractor competes by first creating a bid against the project, supplying the target `project_id`, the bidding `contractor_id`, and a proposed `duration_days` (a positive integer; a shorter duration ranks better). A new bid starts in `DRAFT` status with a `total_cents` of zero and a `rank_score` of zero; the `rank_score` field is present on every bid from creation and only takes on its computed value when the project is awarded (Section 3.4). The contractor prices the work by adding bid line items, each one referencing the bid through `bid_id` and pricing exactly one scope line through `scope_line_item_id`, with a committed `quantity` greater than zero and a `unit_price_cents` of zero or greater. The server computes each line's `line_total_cents` as that line's `quantity` multiplied by its `unit_price_cents`, rounded half-up to whole cents, and recomputes the bid's `total_cents` on every line addition as the sum of the rounded line totals — again rounding each line before summing.

Submitting a bid moves it from `DRAFT` to `SUBMITTED`. Submission is allowed only while the project is still `OPEN_FOR_BIDS` and the current clock is strictly before the project's `bid_deadline`; a submission attempted at or after the deadline is rejected with `ERR_BID_DEADLINE_PASSED`. Submission additionally requires that the contractor be eligible: the contractor's `qualification_status` must be `QUALIFIED`, the contractor's `trade` must equal the project's `required_trade`, and the contractor's `license_expiry` must be strictly after the project's `bid_deadline`; any of these three failing is reported as `ERR_CONTRACTOR_NOT_QUALIFIED`. The contractor's `average_rating` must also be at least the project's `min_rating`, failing which submission is rejected with `ERR_RATING_BELOW_MINIMUM`. Finally, the bid must be complete: at least one bid line item must exist, and every scope line item of the project must be priced by exactly one bid line item — no scope line left unpriced and no scope line priced more than once. A bid that does not cover the scope exactly once is rejected with `ERR_INCOMPLETE_SCOPE_COVERAGE`.

These submit-time checks are evaluated in a fixed precedence so that the reported error is deterministic. The existence of every referenced resource is confirmed first, then the project-state requirement that the project be `OPEN_FOR_BIDS` (a violation here being an invalid-state condition), then the deadline check yielding `ERR_BID_DEADLINE_PASSED`, then the qualification check yielding `ERR_CONTRACTOR_NOT_QUALIFIED`, then the rating-floor check yielding `ERR_RATING_BELOW_MINIMUM`, and finally the scope-coverage check yielding `ERR_INCOMPLETE_SCOPE_COVERAGE`.

A submitted bid can be pulled back for editing, moving its `status` from `SUBMITTED` to `REVISING`; this is permitted only while the project is still `OPEN_FOR_BIDS` and the current clock is before the `bid_deadline`. Re-submitting a revised bid moves it from `REVISING` back to `SUBMITTED` under the same open-project, before-deadline, and complete-scope-coverage conditions, and recomputes `total_cents` from the current set of bid line items. This revise loop — `SUBMITTED → REVISING → SUBMITTED` — may repeat as long as the window is open. A contractor may instead withdraw a submitted bid, moving its `status` from `SUBMITTED` to the terminal `WITHDRAWN` state, which is allowed as long as the project has not yet been awarded.

### 3.4. Comparing Bids and Awarding the Work

Before awarding, a homeowner may request an advisory ranked comparison of the project's currently submitted bids. This comparison computes, but does not persist, a rank score for each bid in the submitted pool at read time. The same scoring formula is used when the award is actually made, at which point the pool is frozen and the scores are persisted onto the bids.

The rank score is a weighted blend in which **a lower score is better**, computed over the bids that are in `SUBMITTED` status for the project (bids in `DRAFT`, `REVISING`, or `WITHDRAWN` are excluded from the pool). The formula normalizes each bid against the pool. Let the minimum and maximum `total_cents` across the pool define the price range, and the minimum and maximum `duration_days` define the duration range. A bid's price-normalized component is zero when every bid in the pool shares the same total; otherwise it is the bid's `total_cents` minus the pool's minimum total, divided by the pool's maximum total minus its minimum total. The duration-normalized component is computed the same way: zero when all durations are equal, otherwise the bid's `duration_days` minus the pool minimum duration, divided by the pool maximum minus the pool minimum duration. The rating-normalized component is five minus the bidding contractor's `average_rating`, all divided by five — so a higher-rated contractor contributes a smaller, better value. The bid's `rank_score` is then the price component multiplied by 0.5, plus the duration component multiplied by 0.3, plus the rating component multiplied by 0.2, with that sum rounded half-up to four decimal places. The best bid is the one with the lowest `rank_score`; ties are broken first by lower `total_cents`, and any remaining tie by earlier `created_at`.

The advisory comparison applies this formula to whatever bids are submitted at the moment of the read and returns them ranked. When the homeowner awards the project, the formula is applied over the submitted pool frozen at award time, and the resulting `rank_score` is persisted on each of those pooled bids; the recorded comparison stands as the audit trail of the decision. The homeowner names the winning bid explicitly and is not obligated to pick the lowest-scoring bid — an override is permitted — but the comparison is still computed and recorded.

Awarding is the system's most consequential cascade and is protected by optimistic concurrency. The award request names the winning `bid_id` and carries `expected_project_version`. The supplied `expected_project_version` must equal the project's current `version`; this optimistic-concurrency check is evaluated before the project-state requirement, so an award carrying a stale version is rejected with `ERR_STALE_PROJECT_VERSION` even when the project has already left `OPEN_FOR_BIDS` (consistent with Section 2.9). The project must then currently be `OPEN_FOR_BIDS`, the named bid must belong to this project and be in `SUBMITTED` status, and the named bid's `total_cents` must not exceed the project's `budget_cap_cents` (otherwise the award is rejected with `ERR_BUDGET_EXCEEDED`). When these hold, the award performs the following in one atomic step: the project's `status` moves from `OPEN_FOR_BIDS` to `AWARDED`; the named bid moves to `AWARDED`; every other bid on the project that is in `SUBMITTED` or `REVISING` status is cascaded to the terminal `REJECTED` state; the project's `awarded_bid_id` is set to the winning bid; `scope_locked` is set to true; the project's `contract_value_cents` is set to the awarded bid's `total_cents` (no change orders exist yet); a fresh escrow is created for the project in `UNFUNDED` status with `funded_cents`, `released_cents`, `retained_cents`, and `available_cents` all zero; and the project's `version` is incremented by one.

A homeowner may instead cancel a project while it is `OPEN_FOR_BIDS`, moving its `status` to the terminal `CANCELLED` state and cascading every bid on the project in `SUBMITTED` or `REVISING` status to `REJECTED`.

### 3.5. Funding Escrow and Starting Work

Once a bid is awarded, the escrow exists but holds no money. The escrow agent funds it by supplying a `deposit_cents` amount, which must exactly equal the project's current `contract_value_cents`; a deposit of any other amount is rejected with `ERR_INSUFFICIENT_ESCROW`. Funding is permitted only while the escrow is `UNFUNDED`. On a successful fund, the escrow's `funded_cents` and `available_cents` are both set to the deposit amount, the escrow's `status` moves from `UNFUNDED` to `FUNDED`, and the project's `status` bubbles up from `AWARDED` to `IN_PROGRESS`. Work — the draw pipeline — can begin only once the project is `IN_PROGRESS`.

### 3.6. The Draw Pipeline: Request, Approve, Pay

The milestone draw pipeline is how the contractor gets paid as work progresses, and it is governed jointly by the milestone state machine and the escrow ledger.

A contractor requests a draw against a milestone by supplying the project's `project_id`, the target `milestone_id`, and a `conditional_waiver_amount_cents` figure. The request is admissible only when the project is `IN_PROGRESS`, and only for the lowest-`sequence` milestone of the project that is still in `PENDING` status; requesting a draw against any other milestone — including skipping ahead — is rejected with `ERR_MILESTONE_OUT_OF_ORDER`. At request time the server computes the draw's amounts and freezes them onto the draw. The `gross_amount_cents` is the project's `contract_value_cents` multiplied by the milestone's `release_pct`, rounded half-up to whole cents, read at the request instant. Whether this draw is the final one is decided by comparing the milestone's `sequence` to the highest sequence among the project's milestones: the draw against the highest-sequence milestone is the final draw. For a non-final draw the `retainage_cents` is the `gross_amount_cents` multiplied by the retainage rate of ten percent, rounded half-up to whole cents — the rounding is applied to the retainage figure and then that rounded retainage is subtracted; for the final-sequence milestone the `retainage_cents` is zero. The `net_release_cents` is the `gross_amount_cents` minus the `retainage_cents`. These frozen amounts are deliberately not re-opened later: a change order approved after a draw has been requested does not retroactively alter that already-requested draw.

A draw request must be accompanied by a conditional lien waiver: the `conditional_waiver_amount_cents` supplied with the request must equal the draw's computed `net_release_cents`, otherwise the request is rejected with `ERR_LIEN_WAIVER_REQUIRED`. On a successful request, three things happen together: the draw is created in `REQUESTED` status with the computed amounts and with its originating contractor copied onto the draw's `contractor_id` from the project's awarded-bid contractor; the milestone moves from `PENDING` to `DRAW_REQUESTED`; and a `CONDITIONAL` lien waiver is created in `COLLECTED` status, linked to the draw through the draw's `lien_waiver_id`. A lien waiver, whether created by the system here or filed directly, records its `project_id`, `contractor_id`, the `draw_id` it is tied to, a `waiver_type` of either `CONDITIONAL` or `UNCONDITIONAL`, an `amount_cents`, and a `status` that begins at `COLLECTED` and may later become `VOIDED`.

The homeowner reviews a requested draw. Approving it requires that the draw be in `REQUESTED` status and that the escrow's `available_cents` be at least the draw's `gross_amount_cents`; if the escrow cannot cover the gross amount the approval is rejected with `ERR_INSUFFICIENT_ESCROW`. On approval, the draw moves from `REQUESTED` to `APPROVED`, its milestone moves from `DRAW_REQUESTED` to `APPROVED`, and the draw's `retainage_cents` is moved within the escrow out of `available_cents` and into `retained_cents`. The homeowner may instead reject a requested draw: rejection moves the draw from `REQUESTED` to the terminal `REJECTED` state, returns its milestone from `DRAW_REQUESTED` back to `PENDING` so the draw can be re-requested, and voids the draw's `CONDITIONAL` lien waiver by moving that waiver's `status` to `VOIDED`.

Payment is the escrow agent's act. Before an approved draw can be paid, the contractor must file an `UNCONDITIONAL` lien waiver for that draw whose `amount_cents` equals the draw's `net_release_cents`; if no such unconditional waiver has been collected, the pay attempt is rejected with `ERR_LIEN_WAIVER_REQUIRED`. Paying an approved draw moves it from `APPROVED` to the terminal `PAID` state, moves its milestone from `APPROVED` to the terminal `PAID` state, and moves the draw's `net_release_cents` within the escrow out of `available_cents` and into `released_cents`. If — and only if — the paid draw is the one against the final-sequence milestone, the retainage that has been accumulating is released at this moment: the entire `retained_cents` balance is added to `released_cents` and `retained_cents` is reset to zero.

### 3.7. Change Orders During Construction

While a project is `IN_PROGRESS`, either the homeowner or the awarded contractor may propose a change order against the awarded bid, supplying the `project_id`, the awarded `bid_id`, a `description` of the scope change, and a signed `delta_cents` — positive to increase the contract value, negative to decrease it. The propose operation itself imposes no project-state or bid-state precondition: it only confirms the referenced `project_id` and `bid_id` exist and the caller's ownership (a homeowner owns the named project, a contractor owns the named bid), and does not require the project to be `IN_PROGRESS` nor verify that the named bid is the project's awarded bid; the `IN_PROGRESS` requirement is enforced only at approve/reject time. A new change order begins in `PROPOSED` status.

Only the homeowner approves or rejects a change order. Rejecting a proposed change order moves it from `PROPOSED` to the terminal `REJECTED` state and requires only that the project be `IN_PROGRESS`. Approving a change order is the second optimistic-concurrency-guarded operation: the approval carries `expected_bid_version`, which must equal the awarded bid's current `version`, and a mismatch is rejected with `ERR_STALE_BID_VERSION`. Approval additionally requires that the project be `IN_PROGRESS` and that the resulting contract value stay within two bounds: the project's `contract_value_cents` plus the change order's `delta_cents` must not exceed the project's `budget_cap_cents`, and that same sum must be at least the escrow's `released_cents` plus its `retained_cents` — a decrease may not shrink the contract below money already committed to the contractor. Either bound being violated is reported as `ERR_BUDGET_EXCEEDED`. On approval, the change order moves from `PROPOSED` to `APPROVED`, the project's `contract_value_cents` is increased by the `delta_cents` (a negative delta decreasing it), and the awarded bid's `version` is incremented by one — which is precisely what makes a second, stale approval fail.

### 3.8. Completion and Contractor Rating

A homeowner completes a project, moving its `status` from `IN_PROGRESS` to the terminal `COMPLETED` state, only when every milestone of the project is in `PAID` status and the escrow's `retained_cents` has been fully released back to zero. Completion also moves the escrow's `status` to the terminal `CLOSED` state.

After a project is completed, the homeowner rates the awarded contractor by supplying a `stars` value between one and five. Rating adds the new star value to the contractor's `rating_sum`, increments the contractor's `rating_count` by one, and recomputes the contractor's `average_rating` as `rating_sum` divided by `rating_count`, rounded half-up to two decimal places — or zero when the contractor has no ratings yet. This average is the same reputation figure used as the rating floor at bid-submission time and as the reputation term in the bid rank score.

### 3.9. Disputes: Freezing and Resolving

Either the homeowner or the contractor may raise a dispute over a draw, supplying the `project_id`, a `subject_type` that must be one of `DRAW` or `CHANGE_ORDER`, the `subject_id` of the disputed draw, a `raised_by` value of either `HOMEOWNER` or `CONTRACTOR`, and a free-text `reason`. Regardless of the `subject_type` value supplied, the `subject_id` is always resolved as a draw: it must name an existing draw (otherwise `ERR_NOT_FOUND`), and the dispute freeze and resolve cascades described below act on that draw and its milestone. Raising a dispute is admissible when the project is `IN_PROGRESS`, and the subject draw belongs to the project and is in `REQUESTED` or `APPROVED` status. A new dispute starts in `OPEN` status with its `resolution` unset. Raising it freezes the workflow: the project's `status` moves to `DISPUTED`, the subject draw's `status` cascades to `DISPUTED`, and that draw's milestone `status` cascades to `DISPUTED`.

A `PlatformAdmin` arbitrates an open dispute by supplying a `resolution` of either `UPHELD` or `OVERTURNED`. Resolving moves the dispute from `OPEN` to the terminal `RESOLVED` state, records the supplied outcome in `resolution`, and returns the project's `status` from `DISPUTED` back to `IN_PROGRESS`. The two outcomes cascade differently and with equal force. When the resolution is `UPHELD`, the contractor's position stands: the disputed draw's `status` is restored to `APPROVED` and its milestone's `status` is restored to `APPROVED`. When the resolution is `OVERTURNED`, the draw is unwound: the disputed draw's `status` becomes the terminal `REJECTED`, its milestone's `status` returns to `PENDING`, the draw's `CONDITIONAL` lien waiver is voided to `VOIDED`, and — if the draw had been `APPROVED` before the dispute froze it — the draw's `retainage_cents` is returned within the escrow from `retained_cents` back to `available_cents`, undoing the retainage hold that approval had created.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource or add a new resource to a collection return `201 Created`. Operations that modify an existing resource — including all state transitions and the test-driving clock control — return `200 OK`. A request that fails authentication, authorization, validation, a state precondition, or an optimistic-concurrency check returns the appropriate 4xx status from the catalogue in Section 5 and mutates nothing.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/homeowners` | Register a homeowner | Anonymous |
| GET | `/homeowners/{id}` | Fetch a homeowner | Homeowner, PlatformAdmin |
| POST | `/contractors` | Register a contractor (starts PENDING) | Anonymous |
| GET | `/contractors/{id}` | Fetch a contractor | Contractor, Homeowner, PlatformAdmin |
| GET | `/contractors` | List contractors, optionally filtered | Homeowner, PlatformAdmin |
| POST | `/contractors/{id}/qualify` | Qualify or re-qualify a contractor | PlatformAdmin |
| POST | `/contractors/{id}/suspend` | Suspend a qualified contractor | PlatformAdmin |
| POST | `/contractors/{id}/revoke` | Revoke a suspended contractor | PlatformAdmin |
| POST | `/projects` | Create a project in DRAFT | Homeowner |
| GET | `/projects/{id}` | Fetch a project | Homeowner, Contractor, PlatformAdmin |
| GET | `/projects` | List projects, optionally filtered | Homeowner, Contractor, PlatformAdmin |
| POST | `/projects/{id}/scope-line-items` | Add a scope line item to a DRAFT project | Homeowner |
| GET | `/projects/{id}/scope-line-items` | List a project's scope line items | Homeowner, Contractor, PlatformAdmin |
| GET | `/scope-line-items/{id}` | Fetch a single scope line item | Homeowner, Contractor, PlatformAdmin |
| GET | `/scope-line-items/{id}/bid-line-items` | List every bid line that prices this scope line | Homeowner, Contractor, PlatformAdmin |
| POST | `/projects/{id}/milestones` | Add a milestone to a DRAFT project | Homeowner |
| GET | `/projects/{id}/milestones` | List a project's milestones (ascending sequence) | Homeowner, Contractor, PlatformAdmin |
| GET | `/projects/{id}/estimate` | Computed homeowner estimate over scope line items | Homeowner, PlatformAdmin |
| POST | `/projects/{id}/open` | Open a project for bids | Homeowner |
| GET | `/projects/{id}/bid-comparison` | Advisory ranked comparison of SUBMITTED bids | Homeowner, PlatformAdmin |
| POST | `/projects/{id}/award` | Award a named bid (OCC-guarded) | Homeowner |
| POST | `/projects/{id}/cancel` | Cancel an OPEN_FOR_BIDS project | Homeowner |
| POST | `/projects/{id}/complete` | Complete an IN_PROGRESS project | Homeowner |
| POST | `/projects/{id}/rate-contractor` | Rate the awarded contractor on a COMPLETED project | Homeowner |
| POST | `/bids` | Create a DRAFT bid for a project | Contractor |
| GET | `/bids/{id}` | Fetch a bid | Contractor, Homeowner, PlatformAdmin |
| GET | `/bids` | List bids, filterable by project or contractor | Contractor, Homeowner, PlatformAdmin |
| POST | `/bids/{id}/line-items` | Add a priced line to a DRAFT/REVISING bid | Contractor |
| GET | `/bids/{id}/line-items` | List a bid's line items | Contractor, Homeowner, PlatformAdmin |
| POST | `/bids/{id}/submit` | Submit a DRAFT or REVISING bid | Contractor |
| POST | `/bids/{id}/revise` | Move a SUBMITTED bid back to REVISING | Contractor |
| POST | `/bids/{id}/withdraw` | Withdraw a SUBMITTED bid before award | Contractor |
| GET | `/escrows/{id}` | Fetch an escrow account | Homeowner, EscrowAgent, PlatformAdmin |
| GET | `/escrows` | List escrows, filterable by project | Homeowner, EscrowAgent, PlatformAdmin |
| POST | `/escrows/{id}/fund` | Fund escrow; moves project to IN_PROGRESS | EscrowAgent |
| POST | `/draws` | Request a milestone draw; files conditional waiver | Contractor |
| GET | `/draws/{id}` | Fetch a draw | Contractor, Homeowner, EscrowAgent, PlatformAdmin |
| GET | `/draws` | List draws, filterable by project/milestone/contractor/waiver | Contractor, Homeowner, EscrowAgent, PlatformAdmin |
| POST | `/draws/{id}/approve` | Approve a requested draw; moves retainage to held | Homeowner |
| POST | `/draws/{id}/reject` | Reject a requested draw; voids the conditional waiver | Homeowner |
| POST | `/draws/{id}/pay` | Pay an approved draw once unconditional waiver collected | EscrowAgent |
| POST | `/lien-waivers` | File an unconditional lien waiver for a draw | Contractor |
| GET | `/lien-waivers/{id}` | Fetch a lien waiver | Contractor, Homeowner, EscrowAgent, PlatformAdmin |
| GET | `/lien-waivers` | List lien waivers, filterable by project/contractor/draw | Contractor, Homeowner, EscrowAgent, PlatformAdmin |
| POST | `/change-orders` | Propose a change order against the awarded bid | Homeowner, Contractor |
| GET | `/change-orders/{id}` | Fetch a change order | Homeowner, Contractor, PlatformAdmin |
| GET | `/change-orders` | List change orders, filterable by project or bid | Homeowner, Contractor, PlatformAdmin |
| POST | `/change-orders/{id}/approve` | Approve a change order (OCC on awarded bid) | Homeowner |
| POST | `/change-orders/{id}/reject` | Reject a proposed change order | Homeowner |
| POST | `/disputes` | Raise a dispute over a draw | Homeowner, Contractor |
| GET | `/disputes/{id}` | Fetch a dispute | Homeowner, Contractor, PlatformAdmin |
| GET | `/disputes` | List disputes, filterable by project or subject draw | Homeowner, Contractor, PlatformAdmin |
| POST | `/disputes/{id}/resolve` | Arbitrate a dispute UPHELD or OVERTURNED | PlatformAdmin |
| POST | `/_clock/set_current_utc` | Set the server's current UTC clock (test-driving) | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_PROJECT_VERSION` | 412 Precondition Failed |
| `ERR_STALE_BID_VERSION` | 412 Precondition Failed |
| `ERR_BID_DEADLINE_PASSED` | 409 Conflict |
| `ERR_CONTRACTOR_NOT_QUALIFIED` | 409 Conflict |
| `ERR_RATING_BELOW_MINIMUM` | 409 Conflict |
| `ERR_INCOMPLETE_SCOPE_COVERAGE` | 422 Unprocessable Entity |
| `ERR_LIEN_WAIVER_REQUIRED` | 422 Unprocessable Entity |
| `ERR_MILESTONE_OUT_OF_ORDER` | 409 Conflict |
| `ERR_MILESTONE_SEQUENCE_TAKEN` | 409 Conflict |
| `ERR_MILESTONE_PCT_INVALID` | 422 Unprocessable Entity |
| `ERR_BUDGET_EXCEEDED` | 409 Conflict |
| `ERR_INSUFFICIENT_ESCROW` | 409 Conflict |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
