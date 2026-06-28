# Yearbook Production API — Product Requirements Document

## 1. Introduction

This document specifies the Yearbook Production API, a back-office platform that carries a school yearbook from an empty page ladder all the way through to the moment a finished book is handed to the buyer who pre-ordered it. The domain mirrors the workflow of a commercial yearbook plant (in the Jostens mold): a faculty adviser lays out the page ladder and assigns staff to produce each page; contributors submit photos and quotes; staff curate and approve those assets; sponsors buy advertising space; families pre-purchase copies, optionally with a foil name stamp; and once every page is approved the book is proofed, frozen, submitted to the plant, printed, shipped, and distributed.

The platform exists to keep four parallel concerns in lockstep that, on paper, are easy to drift out of sync: the **content pipeline** (pages and the submissions that fill them), the **production pipeline** (proof rounds, plant submission, and the print run), the **commercial pipeline** (ad contracts and pre-sale orders), and the **financial rollup** (ad revenue, pre-sale revenue, and plant production cost). A central goal is determinism: pre-sale pricing tiers and assignment deadlines are evaluated against a server-controlled logical clock rather than wall-clock time, so the same sequence of requests always produces the same money and the same state. The sections below define the global request/response contract first, then the cross-cutting principles that govern consistency and money, and finally the business workflows themselves.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API. The API is mounted under the `/yearbooks` path prefix.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated through two mandatory HTTP headers. `X-User-ID` identifies the acting user, and `X-User-Role` declares the operational capacity under which they are acting. If either header is missing, the request is rejected with `ERR_UNAUTHENTICATED`. When the headers are present but the declared role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN`.

The system recognizes exactly four roles, spelled precisely as follows: `Adviser`, `Staff`, `Contributor`, and `SalesRep`. The **Adviser** is the faculty owner of the project — they own the ladder, staff assignments, the proof and plant flow, and the print and delivery lifecycle, and they alone may drive the logical clock. **Staff** members produce the pages assigned to them and review the contributor submissions attached to those pages. A **Contributor** is a student or parent who submits photos and quotes. A **SalesRep** sells advertising contracts and pre-sale book orders.

All four roles are **opaque operator identities**: for each of `Adviser`, `Staff`, `Contributor`, and `SalesRep`, the `X-User-ID` value is an operator identifier that is not tied to any persisted entity's `id`. The server does not compare `X-User-ID` to any stored record to decide ownership; authorization is determined purely by whether the declared `X-User-Role` is permitted for the operation. Where a submission or an assignment records who acted, it does so through explicit body fields (such as `contributor_id` on a submission or `staff_user_id` on a staff assignment) rather than by interpreting the authentication header.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return; if it is not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0, with a minimum of 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order.

Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and the Logical Clock

Every entity in the system — Yearbooks, ladder pages, submissions, staff assignments, ad contracts, proofs, pre-sale orders, print runs, and distribution records — carries a system-generated `id` formatted as a UUID, with no type prefix, and a `created_at` timestamp expressed as an ISO 8601 UTC value with three fractional digits. All of these entities are mutable resources, and so each also carries an `updated_at` timestamp (an ISO 8601 UTC value, refreshed on every change to the resource) and an integer `version` that begins at 1 on creation and increments by one on every subsequent mutation, including mutations that only touch derived fields. There are no creation-immutable entities in this domain; every resource exposes all four of `id`, `created_at`, `updated_at`, and `version`.

Because many decisions in this domain depend on time — which pre-sale pricing tier an order falls into, and whether a staff assignment's deadline is already in the past — the server runs a **logical clock** rather than reading wall-clock time. At startup the clock reads exactly `2026-01-01T00:00:00Z`, and until it is explicitly advanced it remains at that value and never falls back to the host's real time. An adviser-only test-driving capability sets the clock to a supplied `to_iso8601` instant and returns the new clock value as `now_iso`. Every timestamp the system stamps onto a record (such as a pre-sale order's `ordered_at_iso`) is read from this logical clock.

### 2.5. Hierarchical Consistency and Derived-Field Reconciliation

The yearbook is the root of a hierarchy. Ladder pages, staff assignments, ad contracts, proofs, pre-sale orders, print runs, and distribution records all hang off a single yearbook, and submissions hang off a ladder page. Several fields on the yearbook are **derived** — they are never written directly by a client but are recomputed by the server whenever an underlying event changes them. Whenever the server recomputes a derived field on an entity, that recomputation is a mutation of the entity: it refreshes `updated_at` and increments `version`, exactly as a direct edit would. The same holds for cascade transitions the server performs automatically: when an operation flips a child or sibling entity's state without an explicit client request on that entity, the affected entity's `updated_at` and `version` move accordingly.

Requests that target a nested resource validate the path from left to right. A path such as a page beneath a yearbook is checked yearbook-first: if the yearbook portion of the path does not resolve to a real record, the request fails with `ERR_NOT_FOUND` before the page portion is even consulted, and only once the yearbook resolves does the server attempt to locate the page. Foreign-key targets named in the request body — for example the `ladder_page_id` a sponsor contract points at, or the `staff_assignment_id` supplied when assigning a page — are existence-checked separately, and a missing body-referenced target yields `ERR_REFERENCE_NOT_FOUND` (also a 404).

### 2.6. Validation Ordering

When several checks could apply to a single request, the server evaluates them in a fixed priority order, and the first failure is the one returned. The order is: first, authentication — both `X-User-ID` and `X-User-Role` present, else `ERR_UNAUTHENTICATED`; second, authorization — the declared role is permitted for the operation, else `ERR_FORBIDDEN`; third, existence of every path-referenced resource (validated left to right), else `ERR_NOT_FOUND`; fourth, existence of every body-referenced foreign-key target, else `ERR_REFERENCE_NOT_FOUND`; fifth, structural validity of the request body — required fields present, enumerated values legal, numbers within their declared ranges — else `ERR_INVALID_REQUEST` (HTTP 422); sixth, that the target resource is in a state from which the requested transition is defined, else `ERR_INVALID_STATE` (HTTP 409); seventh, the optimistic-concurrency version check on guarded writes, else `ERR_STALE_VERSION` (HTTP 412). Domain-specific business rules (pre-sale window, ad-page section, plant-frozen, submission completeness, and so on) are evaluated after these foundational checks, each returning its own dedicated error described in the workflows below.

This ordering matters in practice: an authentication failure always wins over an authorization failure, a not-found always wins over a malformed body, and a malformed body always wins over a state-transition rejection. A request that is both unauthenticated and malformed surfaces `ERR_UNAUTHENTICATED`, never `ERR_INVALID_REQUEST`.

### 2.7. Money, Counts, and Rounding

All monetary amounts in the system are stored and returned as **integer cents** — list and net ad prices, pre-sale totals, unit and production costs are all whole-cent integers. Two of the pricing calculations involve a multiplicative discount that can land between cents; in every such case the system rounds the result to a whole cent using the **round half up** convention (a value exactly on the half-cent boundary rounds away from zero, to the larger magnitude). Where a calculation pins the order in which rounding happens, that order is part of the contract and is stated with the workflow. Counts (page counts, submission counts, quantities) are exact integers and involve no rounding. Production cost is computed with exact integer arithmetic and needs no rounding at all.

### 2.8. Optimistic Concurrency on the Print Run

Committing the authoritative print run is the one write in this system guarded by optimistic concurrency control, because it is the single irreversible commitment of money against the yearbook. A request to commit a print run must carry `expected_yearbook_version`, and this field is required — the create cannot be made without it. The server compares `expected_yearbook_version` against the target yearbook's current `version`. If they differ — meaning another writer has advanced the yearbook's version since the client last read it (for instance by having already committed the one authoritative print run, which legitimately moves the yearbook into the `PRINTING` posture and bumps its `version`) — the commit is rejected with `ERR_STALE_VERSION` and HTTP status 412, so the client cannot overwrite a print-run commitment it never observed. No other endpoint in the system accepts or requires a version field; only the print-run commit is OCC-guarded.

## 3. Business Logic & Workflows

### 3.1. Founding the Yearbook and Building the Ladder

An `Adviser` opens a production project by creating a **Yearbook**, supplying the `school_name`, the `academic_year` (for example `2025-2026`), a `target_page_count`, the plant's per-copy `unit_cost_cents`, and the two boundaries of the pre-sale window, `presale_open_iso` and `presale_close_iso`. The `target_page_count` must be a positive number and, because pages are bound in four-page signatures, must be evenly divisible by four; a value that is not greater than zero or not divisible by four is a malformed body and is rejected with `ERR_INVALID_REQUEST`. A newly created yearbook starts with `production_phase` equal to `LADDER_BUILD`, all of its derived counts and revenue figures (`ladder_filled_count`, `ad_revenue_cents`, `presale_revenue_cents`, `production_cost_cents`) at zero, `ladder_complete` false, and `version` at 1.

The adviser then populates the **page ladder** one page at a time. Each **LadderPage** belongs to its yearbook (carrying a `yearbook_id`) and is created with a `page_number`, a `section`, a `template_code`, and optionally a `spread_span`, a `required_submission_count`, and an initial `assigned_staff_id`. The `page_number` is a one-based ordinal slot, unique within the yearbook, and must fall within the ladder bounds — at least 1 and no greater than the yearbook's `target_page_count`. The `section` is one of `STUDENT_LIFE`, `ACADEMICS`, `SPORTS`, `CLUBS`, `ADS`, or `SIGNATURE`. The `template_code` names the layout applied to the page (for example `T-2COL` or `T-COLLAGE`). The `spread_span` records how many consecutive page slots the layout occupies and must be either 1 (a single page) or 2 (a double-page spread); when omitted it defaults to 1. The `required_submission_count` is how many approved submissions the page needs before it may be approved; it must be zero or greater and defaults to 1 when omitted.

A page's spread occupies the slots from its `page_number` through `page_number + spread_span - 1`. The server enforces that this occupied range stays inside the ladder: if any slot in the range would exceed the `1`-through-`target_page_count` bounds the page is rejected with `ERR_PAGE_NUMBER_OUT_OF_BOUNDS`. It also enforces that the occupied range does not overlap any slot already occupied by another page on the same yearbook; an overlap is rejected with `ERR_PAGE_NUMBER_CONFLICT`. Each newly created page begins in `DRAFT` status, and adding it recomputes the yearbook's `ladder_filled_count`, its `ladder_complete` flag, and its `production_phase`.

The number of pages attached to a yearbook is tracked on the yearbook as `ladder_filled_count`, which is simply the count of LadderPage rows whose `yearbook_id` is that yearbook. The yearbook is considered ladder-complete — its `ladder_complete` flag is true — exactly when `ladder_filled_count` equals the `target_page_count`; at any other count it is false.

### 3.2. Filling Pages: Contributor Submissions and Staff Review

A `Contributor` populates a page by lodging a **Submission** against it. A submission references its page through `ladder_page_id` and is created with a `kind` of either `PHOTO` or `QUOTE`, a `contributor_id` identifying who submitted it, and an `asset_ref` carrying either the storage reference of a photo or the text of a quote. Every submission also carries a `review_note` that a reviewer records when approving or rejecting; it defaults to an empty string. A new submission begins life in `PENDING`.

A `Staff` member curates the submissions on the pages they work. Reviewing a pending submission, the staff member either approves it, moving it from `PENDING` to `APPROVED`, or rejects it, moving it from `PENDING` to `REJECTED`; a `review_note` may accompany either action. A staff member may also un-approve an asset that was previously approved, moving it from `APPROVED` back to `REJECTED` — a compensating action that restores the page's submission deficit. When a `Contributor` resubmits a corrected asset, the submission moves from `REJECTED` back to `PENDING`, optionally carrying a fresh `asset_ref`; this is the revision loop that lets a contributor fix and re-offer a rejected asset.

Approving and un-approving submissions is only permitted while the parent page is still open for editing — that is, while the page's `status` is one of `DRAFT`, `IN_REVIEW`, or `CHANGES_REQUESTED`. Likewise, a contributor may only resubmit against a page in one of those three statuses. If the parent page has already reached `APPROVED` or `LOCKED`, any attempt to approve, reject, or resubmit one of its submissions is rejected with `ERR_PAGE_LOCKED_FOR_SUBMISSIONS`. Each page tracks `approved_submission_count`, the number of its submissions currently in `APPROVED`; approving a submission increases this count by one and un-approving a previously approved submission decreases it by one, with the page's count always recomputed from the live set of its approved submissions.

### 3.3. Staffing the Pages: Assignments and Deadlines

The adviser staffs production by creating **StaffAssignments**, each scoped to a yearbook through `yearbook_id`. An assignment is created with the `staff_user_id` it represents (the opaque operator identifier of the staff member), a `role_title` drawn from `EDITOR`, `PHOTOGRAPHER`, `SECTION_LEAD`, or `SIGNATURE_COORDINATOR`, and a `deadline_iso` by which that staff member's assigned pages must reach `APPROVED`. A deadline that has already passed relative to the logical clock — that is, a `deadline_iso` earlier than the current clock instant — cannot be set on a new assignment and is rejected with `ERR_DEADLINE_IN_PAST`. A fresh assignment starts `ACTIVE` with its `assigned_page_count` at zero.

A page is staffed by assigning a `staff_assignment_id` to it, which sets the page's `assigned_staff_id` and recomputes that assignment's `assigned_page_count` — the number of ladder pages whose `assigned_staff_id` points at that assignment. An adviser may later release an assignment, moving its `status` from `ACTIVE` to `RELEASED` when the staff member is done.

A page becomes eligible to enter review only when it carries an `assigned_staff_id` and the referenced staff assignment is currently `ACTIVE`. When `Staff` submits a page for the adviser's review — advancing it from `DRAFT` to `IN_REVIEW`, or from `CHANGES_REQUESTED` back to `IN_REVIEW` after edits — the server first checks that the page's `approved_submission_count` is at least its `required_submission_count`; a page short of its required approvals is rejected with `ERR_SUBMISSIONS_INCOMPLETE`. On the very first submission for review out of `DRAFT`, the server additionally requires that the page has an `assigned_staff_id` whose staff assignment is `ACTIVE`; a page lacking an active assigned staff member is rejected with `ERR_PAGE_UNASSIGNED`.

### 3.4. Adviser Review: Approving and Reopening Pages

Once a page is `IN_REVIEW`, the `Adviser` either requests changes or approves it. Requesting changes moves an `IN_REVIEW` page to `CHANGES_REQUESTED`, sending it back to staff for another revision pass. Approving a page requires, once more, that its `approved_submission_count` is at least its `required_submission_count`; if not, the approval is rejected with `ERR_SUBMISSIONS_INCOMPLETE`. A successful approval moves the page from `IN_REVIEW` to `APPROVED` and recomputes the yearbook's `production_phase`.

The adviser may reopen an already-approved page, moving it from `APPROVED` to `CHANGES_REQUESTED` — but only while the plant copy has not been frozen. Concretely, reopening an approved page is permitted only when no proof on the parent yearbook is in `PLANT_SUBMITTED` or `PLANT_APPROVED`; if such a proof exists, the reopen is rejected with `ERR_PLANT_FROZEN`. Plant submission, described below, automatically freezes every approved page into `LOCKED`. A `LOCKED` page is terminal for ordinary editing: because a page only reaches `LOCKED` by way of a plant submission, the parent yearbook always has a `PLANT_SUBMITTED` or `PLANT_APPROVED` proof while the page is locked, so an attempt to reopen a `LOCKED` page is always rejected — and it is rejected specifically with the domain-meaningful `ERR_PLANT_FROZEN` rather than a generic invalid-state error. The reopen action is therefore defined out of both `APPROVED` and `LOCKED`, with the frozen-plant guard being the gate that the `APPROVED` case can pass pre-plant and the `LOCKED` case can never pass.

### 3.5. Selling the Book: Ads and Pre-Sale Orders

A `SalesRep` monetizes the yearbook along two tracks. The first is **AdContracts**. A sponsor contract is scoped to a yearbook (`yearbook_id`) and is created against a specific advertising page by `ladder_page_id`, carrying the `sponsor_name`, a `size` of `FULL`, `HALF`, or `QUARTER` (the fraction of a page purchased), and an optional `discount_pct`. The `discount_pct` is a fraction between 0 and 0.5 inclusive; a value below 0 or above 0.5 is rejected with `ERR_INVALID_REQUEST`, and when omitted it defaults to 0. At creation the server computes the contract's `list_price_cents` and `net_price_cents`, and the contract begins in `DRAFT`.

The `list_price_cents` is fixed by the size tier alone: a `FULL` page lists at 40000 cents, a `HALF` page at 24000 cents, and a `QUARTER` page at 14000 cents. The `net_price_cents` is then the discounted price, and the rounding order here is pinned: take the integer `list_price_cents`, multiply it by one minus the `discount_pct`, and round that single product to a whole cent using round half up — in one rounding step. The list price is not rounded beforehand; there is exactly one rounding, applied to the discounted amount. Both prices are frozen at creation and are not recomputed by any later event.

Signing a contract advances it from `DRAFT` to `SIGNED`, but only if the page it references is in the `ADS` section; a contract whose referenced page's `section` is not `ADS` is rejected at sign time with `ERR_AD_PAGE_NOT_ADS_SECTION`. Signing adds the contract's `net_price_cents` to the yearbook's running `ad_revenue_cents`. A signed contract can be placed, advancing from `SIGNED` to `PLACED`, but only once its referenced page has reached `APPROVED`; placing against a page that is not `APPROVED` is rejected with `ERR_AD_PAGE_NOT_APPROVED`. A contract may be voided from either `DRAFT` or `SIGNED`, moving it to `VOIDED`; voiding a `DRAFT` contract has no revenue effect, but voiding a `SIGNED` contract is a compensating action that subtracts its `net_price_cents` back out of the yearbook's `ad_revenue_cents`, restoring the figure to its pre-sign value. The yearbook's `ad_revenue_cents` is, in effect, the running sum of `net_price_cents` over its contracts currently in `SIGNED` or `PLACED`.

The second track is **PreSaleOrders**. A pre-sale order is scoped to a yearbook (`yearbook_id`) and created with a `buyer_name`, a `quantity` of at least 1, an optional `personalize` flag (default false), and an optional `stamp_name` for the foil name stamp. When `personalize` is true the `stamp_name` must be a non-empty string; a personalized order with an empty `stamp_name` is rejected with `ERR_INVALID_REQUEST`. The `stamp_name` defaults to an empty string. On creation the server stamps `ordered_at_iso` from the logical clock, derives the `price_tier`, computes `total_price_cents`, and sets the order's `status` to `PLACED`.

The pricing tier and total are computed as follows. The order time is the `ordered_at_iso` just stamped. If that time is before the yearbook's `presale_open_iso`, the order is rejected outright with `ERR_PRESALE_NOT_OPEN` — the window has not opened. If the order time is at or after `presale_open_iso` but strictly before `presale_close_iso`, the `price_tier` is `EARLY`. If the order time is at or after `presale_close_iso`, the `price_tier` is `STANDARD`. The per-copy base is 6500 cents in the `EARLY` tier and 8000 cents in the `STANDARD` tier. When `personalize` is true a name-stamp fee of 500 cents is added per copy; otherwise no stamp fee applies. The per-copy price is therefore the tier base plus, if personalized, the 500-cent stamp fee. The gross is that per-copy price multiplied by `quantity`. A bulk discount of 10 percent applies to the gross only when `quantity` is at least 5: in that case the discount is 10 percent of the gross, rounded to a whole cent with round half up, and `total_price_cents` is the gross minus that discount; for any quantity below 5 there is no discount and `total_price_cents` equals the gross.

Paying a pre-sale order moves it from `PLACED` to `PAID` and adds its `total_price_cents` to the yearbook's `presale_revenue_cents`. An order may be cancelled from `PLACED` (moving straight to `CANCELLED` with no revenue effect, since it was never paid) or from `PAID` (moving to `CANCELLED` and compensating by subtracting its `total_price_cents` back out of `presale_revenue_cents`, restoring the pre-pay figure). The yearbook's `presale_revenue_cents` is the running sum of `total_price_cents` over its orders currently in `PAID` or `FULFILLED`. Cancelling a `PAID` order is blocked once the book has gone out the door: if any print run on the yearbook has reached `SHIPPED` or `DELIVERED`, the cancel is rejected with `ERR_ALREADY_DISTRIBUTED`.

### 3.6. Proofing and Submitting to the Plant

Production review is organized into **Proof** rounds. Each proof is scoped to its yearbook (`yearbook_id`), carries an optional `reviewer_note` (the adviser's note on the round, defaulting to an empty string), and is stamped with a `round_number` — a one-based ordinal that is one greater than the highest round number among existing proofs on the yearbook, so each new round increments. A new proof opens in `OPEN`.

While a round is `OPEN`, the adviser may request changes, moving it to `CHANGES_REQUESTED`, and later reopen it, moving it back from `CHANGES_REQUESTED` to `OPEN` once corrections are in — the proof revision loop. A `reviewer_note` may accompany a request-changes action.

The pivotal step is submitting the proof to the plant, which advances an `OPEN` proof to `PLANT_SUBMITTED`. This is gated by two completeness checks: the yearbook must be ladder-complete (its `ladder_complete` flag true, i.e. `ladder_filled_count` equals `target_page_count`), otherwise the submission is rejected with `ERR_LADDER_INCOMPLETE`; and every ladder page on the yearbook must be in `APPROVED`, otherwise it is rejected with `ERR_PAGES_NOT_ALL_APPROVED`. When both hold, submitting to the plant cascades: every page currently in `APPROVED` on that yearbook transitions `APPROVED → LOCKED`, freezing the content so no further edits can land after the plant copy is made, and the yearbook's `production_phase` is recomputed to `PLANT`. Once the plant approves the submitted proof, it advances from `PLANT_SUBMITTED` to `PLANT_APPROVED`, and the yearbook's `production_phase` is recomputed to `PRINTING`.

### 3.7. Committing the Print Run, Cost, and Delivery

With a proof plant-approved, the `Adviser` commits the authoritative **PrintRun**. A print run is scoped to a yearbook (`yearbook_id`) and created with the `quantity` of copies to print (at least 1), a `delivery_address`, and the `expected_yearbook_version` that guards the commit as described in §2.8. Committing the run computes its `cost_cents` from the production-cost calculation, snapshots that figure onto the run, mirrors it onto the yearbook's `production_cost_cents`, sets the run's `status` to `COMMITTED`, and increments the yearbook's `version` by one — which is precisely the version advance that a stale concurrent committer will collide with.

The **production cost** the plant charges is the per-copy cost times the committed `quantity`. The per-copy cost is the yearbook's `unit_cost_cents` plus a page-surcharge that is non-linear in page count. The first 96 pages carry no surcharge. Beyond that base allowance of 96 pages, the surcharge accrues per extra four-page signature: take the yearbook's `target_page_count`, subtract the 96-page allowance, divide by 4 pages per signature, and round that quotient up to the next whole number to get the count of extra signatures; multiply that count by 800 cents per extra signature to get the per-copy surcharge. If the page count does not exceed 96 there are no extra signatures and the surcharge is zero. The per-copy cost is `unit_cost_cents` plus this surcharge, and the production cost is that per-copy cost multiplied by the print run's `quantity`. All of this is exact integer arithmetic.

Before any print run exists, an `Adviser` or `SalesRep` can read a forward-looking **cost estimate** for the yearbook. The estimate uses the same per-copy cost formula but substitutes a projected demand for the quantity: the projected quantity is the sum of `quantity` over the yearbook's pre-sale orders currently in `PLACED` or `PAID`. The capability returns this projected `estimated_quantity` alongside the resulting `estimated_cost_cents`. This estimate is forward-looking and need not equal the authoritative committed figure, which is computed from the explicit committed `quantity` at commit time and frozen onto the run.

A committed run is then shipped by the adviser, moving it from `COMMITTED` to `SHIPPED`, and finally delivered, moving it from `SHIPPED` to `DELIVERED`. Delivery is the settlement event. When the run reaches `DELIVERED`, the system cascades: every pre-sale order on the yearbook currently in `PAID` transitions `PAID → FULFILLED`, and each newly fulfilled order spawns a **DistributionRecord**. The yearbook's `production_phase` is then recomputed to `DELIVERED`.

Each **DistributionRecord** is scoped to its yearbook (`yearbook_id`) and to the order it settles (`presale_order_id`). At creation the server copies the order's buyer name into `recipient_name` and the order's quantity into `copies_handed`, and the record is born in `HANDED_OUT`, which is its only and terminal status. Distribution records are server-authored settlement rows; they are created only by the delivery cascade, never directly.

### 3.8. The Yearbook's Production Phase

Throughout all of the above, the yearbook's `production_phase` is a derived posture recomputed after any ladder-page, proof, or print-run transition that could change it. It is evaluated top-down, and the first matching condition wins. If a print run on the yearbook has reached `DELIVERED`, the phase is `DELIVERED`. Otherwise, if a proof on the yearbook is in `PLANT_APPROVED`, the phase is `PRINTING`. Otherwise, if a proof is in `PLANT_SUBMITTED`, the phase is `PLANT`. Otherwise, if the yearbook is ladder-complete and every one of its pages is in `APPROVED` (the count of pages in `APPROVED` equals `ladder_filled_count`) and there is at least one page, the phase is `PROOFING`. Otherwise, if there is at least one page and at least one page is in a status other than `DRAFT`, the phase is `CONTENT`. Otherwise the phase is `LADDER_BUILD`. This single derivation reconciles the content, proof, and print pipelines into one posture the rest of the system can read off the yearbook.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource or add a new resource to a collection return a `201 Created` status code. Operations that modify an existing resource — including state transitions and the logical-clock advance — return a `200 OK` status code. The table below lists the available operations; the request and response details for each are defined by the workflow narratives in §3, not duplicated here.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server logical clock | Adviser |
| POST | `/yearbooks` | Create a Yearbook production project | Adviser |
| GET | `/yearbooks` | List yearbooks | Adviser, Staff, SalesRep, Contributor |
| GET | `/yearbooks/{yearbookId}` | Get a Yearbook with all derived fields | Adviser, Staff, SalesRep, Contributor |
| GET | `/yearbooks/{yearbookId}/cost-estimate` | Forward-looking production cost estimate | Adviser, SalesRep |
| POST | `/yearbooks/pages` | Add a page to a yearbook's ladder | Adviser |
| GET | `/yearbooks/pages` | List ladder pages | Adviser, Staff, SalesRep, Contributor |
| GET | `/yearbooks/pages/{pageId}` | Get a ladder page | Adviser, Staff, SalesRep, Contributor |
| POST | `/yearbooks/pages/{pageId}/assign` | Assign a staff assignment to a page | Adviser |
| POST | `/yearbooks/pages/{pageId}/submit-review` | Submit a page for adviser review | Staff |
| POST | `/yearbooks/pages/{pageId}/request-changes` | Request changes on a page | Adviser |
| POST | `/yearbooks/pages/{pageId}/approve` | Approve a page | Adviser |
| POST | `/yearbooks/submissions` | Submit a photo/quote to a page | Contributor |
| GET | `/yearbooks/submissions` | List submissions | Adviser, Staff, Contributor |
| GET | `/yearbooks/submissions/{submissionId}` | Get a submission | Adviser, Staff, Contributor |
| POST | `/yearbooks/submissions/{submissionId}/approve` | Approve a submission | Staff |
| POST | `/yearbooks/submissions/{submissionId}/reject` | Reject a submission | Staff |
| POST | `/yearbooks/submissions/{submissionId}/resubmit` | Resubmit a rejected asset | Contributor |
| POST | `/yearbooks/staff-assignments` | Create a staff assignment | Adviser |
| GET | `/yearbooks/staff-assignments` | List staff assignments | Adviser, Staff |
| GET | `/yearbooks/staff-assignments/{assignmentId}` | Get a staff assignment | Adviser, Staff |
| POST | `/yearbooks/staff-assignments/{assignmentId}/release` | Release a staff assignment | Adviser |
| POST | `/yearbooks/ad-contracts` | Create an ad/sponsor contract | SalesRep |
| GET | `/yearbooks/ad-contracts` | List ad contracts | Adviser, SalesRep |
| GET | `/yearbooks/ad-contracts/{contractId}` | Get an ad contract | Adviser, SalesRep |
| POST | `/yearbooks/ad-contracts/{contractId}/sign` | Sign an ad contract | SalesRep |
| POST | `/yearbooks/ad-contracts/{contractId}/place` | Place a signed ad contract | SalesRep |
| POST | `/yearbooks/ad-contracts/{contractId}/void` | Void an ad contract | SalesRep |
| POST | `/yearbooks/proofs` | Open a new proof round | Adviser |
| GET | `/yearbooks/proofs` | List proof rounds | Adviser, Staff |
| GET | `/yearbooks/proofs/{proofId}` | Get a proof round | Adviser, Staff |
| POST | `/yearbooks/proofs/{proofId}/request-changes` | Request changes on a proof | Adviser |
| POST | `/yearbooks/proofs/{proofId}/reopen` | Reopen a proof after corrections | Adviser |
| POST | `/yearbooks/proofs/{proofId}/submit-plant` | Submit the proof to the plant | Adviser |
| POST | `/yearbooks/proofs/{proofId}/approve-plant` | Plant-approve the submitted proof | Adviser |
| POST | `/yearbooks/presale-orders` | Place a pre-sale order | SalesRep |
| GET | `/yearbooks/presale-orders` | List pre-sale orders | Adviser, SalesRep |
| GET | `/yearbooks/presale-orders/{orderId}` | Get a pre-sale order | Adviser, SalesRep |
| POST | `/yearbooks/presale-orders/{orderId}/pay` | Mark a pre-sale order paid | SalesRep |
| POST | `/yearbooks/presale-orders/{orderId}/cancel` | Cancel a pre-sale order | SalesRep |
| POST | `/yearbooks/print-runs` | Commit the authoritative print run | Adviser |
| GET | `/yearbooks/print-runs` | List print runs | Adviser |
| GET | `/yearbooks/print-runs/{printRunId}` | Get a print run | Adviser |
| POST | `/yearbooks/print-runs/{printRunId}/ship` | Mark a print run shipped | Adviser |
| POST | `/yearbooks/print-runs/{printRunId}/deliver` | Mark a print run delivered | Adviser |
| GET | `/yearbooks/distribution-records` | List distribution records | Adviser, SalesRep |
| GET | `/yearbooks/distribution-records/{recordId}` | Get a distribution record | Adviser, SalesRep |

List endpoints accept the standard `limit` and `offset` pagination query parameters. In addition, ladder-page listing accepts `yearbook_id` and `assigned_staff_id` filters; submission listing accepts a `ladder_page_id` filter; staff-assignment, ad-contract, proof, pre-sale-order, and print-run listings accept a `yearbook_id` filter; ad-contract listing also accepts a `ladder_page_id` filter; and distribution-record listing accepts `yearbook_id` and `presale_order_id` filters.

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_REFERENCE_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_PRESALE_NOT_OPEN` | 409 |
| `ERR_AD_PAGE_NOT_ADS_SECTION` | 409 |
| `ERR_AD_PAGE_NOT_APPROVED` | 409 |
| `ERR_PLANT_FROZEN` | 409 |
| `ERR_SUBMISSIONS_INCOMPLETE` | 409 |
| `ERR_PAGE_UNASSIGNED` | 409 |
| `ERR_PAGE_LOCKED_FOR_SUBMISSIONS` | 409 |
| `ERR_LADDER_INCOMPLETE` | 409 |
| `ERR_PAGES_NOT_ALL_APPROVED` | 409 |
| `ERR_PAGE_NUMBER_CONFLICT` | 409 |
| `ERR_PAGE_NUMBER_OUT_OF_BOUNDS` | 409 |
| `ERR_DEADLINE_IN_PAST` | 409 |
| `ERR_ALREADY_DISTRIBUTED` | 409 |
