# Seed Library & Plant Swap Program API — Product Requirements Document

## 1. Introduction

A public library district runs a seed library: patrons borrow packets of vegetable, herb, flower, and native-plant seed at the start of the season and are asked — not charged — to save seed from their harvest and bring it back, either to the circulation desk or to the community plant-swap events the district hosts at its branches and partner gardens. The stock is finite, the quality of donated seed is uncertain until a germination assay proves it, and the program's credibility depends on two kinds of discipline that paper ledgers have never managed well: keeping invasive or regionally inappropriate varieties out of circulation, and keeping a small pool of popular varieties fairly shared across hundreds of members.

This document specifies the REST API that backs the program, mounted under the `/api` prefix. It covers the partner-site and membership registries, the seed catalog, lot intake with quarantine and certified germination testing, volunteer-run packet packing, circulation with borrowing limits derived from return behavior, swap events with their intake screening and credit ledger, and the packing-session roster that staffs the operation. Three roles share the work under a deliberate segregation of duties: volunteers record germination assays and pack packets, program administrators certify results and run every lifecycle decision, and members serve themselves at the borrowing and swap counters.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two headers: `X-User-ID` identifies the caller, and `X-User-Role` declares the caller's role. Three roles exist, spelled exactly `Member`, `Volunteer`, and `ProgramAdmin`. A request missing either header, or presenting a role outside this declared set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A properly authenticated caller whose role is not in an endpoint's authorized list is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403).

Identity is anchored differently per role. When `X-User-Role` is `Member`, `X-User-ID` is the `id` of the acting `Member` record; ownership checks on any resource that references a member compare the resource's `member_id` field to `X-User-ID`. When `X-User-Role` is `Volunteer`, `X-User-ID` is the `id` of the acting `Volunteer` record, and ownership checks on packing assignments compare the assignment's `volunteer_id` to `X-User-ID`. When `X-User-Role` is `ProgramAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server never compares it against any entity's `id`.

Self-service is enforced by an ownership rule: a `Member` may act only on resources whose `member_id` equals the presented `X-User-ID`, and a `Volunteer` only on assignments whose `volunteer_id` equals it. Violations are rejected with `ERR_SELF_SERVICE_FORBIDDEN` (HTTP 403). The rule governs exactly ten operations: creating a checkout, returning a checkout, disputing a checkout, submitting a swap-intake item, redeeming credits at an event, withdrawing an intake item, reading one's own member record, reading one's own credit summary, signing up for a packing session, and cancelling a packing assignment. `ProgramAdmin` operators act on behalf of any member or volunteer and are exempt from the ownership comparison, though never from the role-permission check.

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

List endpoints accept two query parameters. `limit` defaults to 10, with a minimum of 1 and a maximum of 100; `offset` defaults to 0. Every list response carries `limit`, `offset`, `total_count`, and `has_more` in its `meta` object. Collections are returned in `created_at` ascending order — oldest first — unless a more specific ordering is pinned by a rule in §3.

### 2.4. Resource Identity, Timestamps, and Versioning

Every persisted resource carries an `id` minted by the server as a bare UUID with no type prefix, a `created_at` timestamp, an `updated_at` timestamp, and an integer `version`. Both timestamps are ISO 8601 UTC values with three fractional digits. `version` increments by one on every mutation of the entity, including mutations delivered through a cascade — when an operation touches several entities, each touched entity's `version` advances and its `updated_at` refreshes. One deliberate exception exists: `CreditEntry` is an append-only ledger row and carries only `id` and `created_at`. It has no `updated_at` and no `version`, because ledger entries are never modified after being appended.

### 2.5. The Logical Clock

All time-dependent behavior in the system — loan due dates, the overdue sweep, session completion eligibility, recency-decayed return scoring — reads a single server-side logical clock, and the server never falls back to wall-clock time. At startup, before any explicit set call, the logical clock reads exactly `2026-08-01T00:00:00Z`. A program-administrator-only test-driving capability advances the clock to a supplied `to_iso8601` instant and reports the resulting `current_utc`; setting the clock mutates no entity.

### 2.6. Numeric Precision and Rounding

Measured percentages — germination results and viability figures — are held at two decimal places, rounded half up. Member return rates and decay-weighted scores are held at four decimal places, rounded half up, and all threshold comparisons against tiers use that rounded four-decimal value. Counts that must be whole — viable seed estimates derived from a percentage, pack-allocation ceilings — are rounded down to the nearest integer. Swap-credit valuations round each item's credit to a whole integer, half up, before any summation. Credit ledger arithmetic is pure integer arithmetic with no rounding. The daily sweep compares timestamps at second precision.

### 2.7. Optimistic Concurrency Control

Two write endpoints are guarded by optimistic concurrency control. Editing a seed variety requires the request to carry `expected_seed_variety_version`, holding the variety `version` the client last observed. Rescheduling or renaming a swap event requires `expected_swap_event_version` in the same sense. In both cases the field is non-optional: if the supplied value does not equal the entity's current `version`, the write is rejected with `ERR_STALE_VERSION` (HTTP 412), protecting the client from overwriting a record it has not observed. A successful guarded write increments the entity's `version`, advancing the watermark every subsequent writer must match. No other endpoint accepts a version field.

### 2.8. Nested Paths and Identifier Resolution

Paths that nest one resource beneath another resolve their identifiers strictly left to right: when a germination assay is recorded beneath a lot, the lot identifier in the path is checked first, and only then the request's own identifiers. An identifier that resolves to no existing entity — whether it appears in the path or in the request body as a foreign key such as `member_id`, `packet_id`, `variety_id`, `site_id`, or `volunteer_id` — is rejected with `ERR_NOT_FOUND` (HTTP 404).

### 2.9. Validation Evaluation Order

Every guarded request passes through a fixed sequence of validation bands, and an earlier failure masks every later check — the response carries the first failing rule's error, never a later one. The bands run in this order:

1. Header presence and role declaration (`ERR_UNAUTHENTICATED`).
2. Role permission for the endpoint (`ERR_UNAUTHORIZED_ROLE`).
3. Left-to-right resolution of path identifiers (`ERR_NOT_FOUND`).
4. Request-body shape: required fields present, types correct, enum values within their declared sets, and numeric ranges respected — `seeds_tested` at least 1, `sprouted_count` no greater than `seeds_tested`, `provisional_viability_pct` between 0 and 100 inclusive, `end_at` strictly after `start_at`, `capacity` at least 1, `credits` at least 1. Malformed bodies draw `ERR_INVALID_REQUEST` (HTTP 400); a value outside an enum's declared set — for `site_type`, `category`, `item_type`, `condition`, `outcome`, `mode`, or any `status` target — draws `ERR_INVALID_ENUM` (HTTP 400).
5. Existence of body-referenced foreign keys (`ERR_NOT_FOUND`).
6. State preconditions for the operation against a non-terminal resource (`ERR_INVALID_STATE`, HTTP 409), including the specialized members of this band: member standing for borrowing (`ERR_MEMBER_SUSPENDED`), lot status for checkout or packing (`ERR_LOT_NOT_ACTIVE`), and intake-open status for submissions and redemptions (`ERR_EVENT_NOT_INTAKE_OPEN`).
7. Safety screens: the invasive-species screen (`ERR_INVASIVE_SPECIES_BLOCKED`, HTTP 422) followed by the regional-appropriateness screen (`ERR_REGION_NOT_APPROVED`, HTTP 422).
8. Uniqueness constraints (`ERR_DUPLICATE_LOT_CODE`, `ERR_DUPLICATE_INTAKE_ITEM`, both HTTP 409).
9. Temporal constraints: event window overlap (`ERR_EVENT_WINDOW_OVERLAP`), session window overlap (`ERR_SESSION_WINDOW_OVERLAP`), and volunteer double-booking (`ERR_VOLUNTEER_DOUBLE_BOOKED`), all HTTP 409.
10. Referential-consistency rules: certification outcome agreement (`ERR_VIABILITY_OUTCOME_MISMATCH`, HTTP 422) and the cancellability precondition (`ERR_EVENT_NOT_CANCELLABLE`, HTTP 409).
11. Fiscal rules: borrow limit (`ERR_BORROW_LIMIT_EXCEEDED`), pack quantity (`ERR_PACK_QUANTITY_EXCEEDS_ALLOCATABLE`), event credit cap (`ERR_EVENT_CREDIT_CAP_EXCEEDED`), redemption sufficiency (`ERR_INSUFFICIENT_CREDITS`), and session capacity (`ERR_SESSION_CAPACITY_FULL`), all HTTP 422.
12. Ownership and self-service (`ERR_SELF_SERVICE_FORBIDDEN`).
13. Optimistic concurrency (`ERR_STALE_VERSION`).
14. Terminal lockdown (`ERR_ALREADY_TERMINAL`, HTTP 409).

Two bands deserve a clarifying word. Band 6 and band 14 are disjoint by construction: when the target entity already sits in a terminal state, any mutation trigger against it is rejected with `ERR_ALREADY_TERMINAL`; when the entity is non-terminal but the trigger is not valid from its current state, the rejection is `ERR_INVALID_STATE`. And because band 12 sits after the fiscal band, an unauthorized self-service attempt on an otherwise-invalid request will surface the earlier business error rather than the ownership failure — that ordering is intentional and tested behavior.

### 2.10. Conservation Invariants

Two quantities are conserved across the entire system, and the invariant is verified after every mutation that moves them. For each seed lot, the number of seeds physically received always equals the sum of three buckets: the seeds still loose in the lot, the seeds currently bound in live packets, and the seeds that have been discarded. No operation creates or destroys seed except an explicit discard move. For each member, the total credits ever earned at swap events always equal the sum of the credits redeemed, the credits expired, the credits revoked, and the outstanding balance; the ledger never loses a credit, it only reclassifies it.

## 3. Business Logic & Workflows

### 3.1. Sites, Membership, and Volunteer Onboarding

The program's physical footprint is the site registry. Registering a site takes a display `name`, a `site_type` of either `LIBRARY_BRANCH` or `GARDEN`, and a `region_zone` hardiness code such as "ZONE_5A" that will later gate which varieties may circulate to members and events homed there. A site also holds a `label_stock_count` — the physical packet-label stock at that location — which defaults to 0, may never go negative, and is debited one label per packet created by packing operations on lots homed at the site. New sites begin `ACTIVE`. An administrator may later patch a site's `name`, `region_zone`, `label_stock_count`, or `status`; moving a site from `ACTIVE` to `INACTIVE` is refused with `ERR_INVALID_STATE` while the site still hosts a swap event in any of `DRAFT`, `SCHEDULED`, `INTAKE_OPEN`, or `INTAKE_CLOSED`, and the reverse move from `INACTIVE` back to `ACTIVE` is unconditional. The site list supports filtering by `status`.

Members are registered with a unique `email`, a `full_name`, and a `home_site_id` pointing at their home branch — the site whose `region_zone` gates variety appropriateness when that member borrows. A fresh member starts `ACTIVE` with every counter at zero: `active_checkout_count`, `overdue_checkout_count`, `terminal_checkout_count`, `verified_return_count`, and all four credit totals; `simple_return_rate` and `decay_weighted_return_score` begin at 0.0; `standing_tier` begins `STANDARD`, which yields an `effective_borrow_limit` of 5. Administrators may update `full_name` or `home_site_id`, and may close a membership from either `ACTIVE` or `SUSPENDED` — but closure is rejected with `ERR_INVALID_STATE` unless the member has no live checkouts (`active_checkout_count` is zero) and no outstanding credit balance (`credits_balance` is zero). `CLOSED` is terminal. The member list is administrator-only and filterable by `home_site_id` and `status`; a member may read only their own record and their own credit summary.

Volunteers onboard in two steps. Registration captures a unique `email` and `full_name` and leaves the record in `APPLIED`; an explicit approval moves it to `ACTIVE`. Only `ACTIVE` volunteers may record germination assays, pack lots, or sign up for packing sessions. Moving a volunteer from `ACTIVE` to `INACTIVE` is refused with `ERR_INVALID_STATE` while the volunteer still holds an assignment in `SIGNUP`; reactivation from `INACTIVE` to `ACTIVE` is unconditional.

### 3.2. The Seed Catalog and Lot Intake

Before any seed enters the building, a librarian describes it in the catalog. Creating a variety takes a `variety_name` (the cultivar, e.g. "Brandywine"), a `species`, a `category` of `VEGETABLE`, `HERB`, `FLOWER`, or `NATIVE`, and a non-empty `approved_zones` array naming every region zone where the variety may circulate. Two flags travel with the variety: `invasive_flag`, defaulting to false, marks species on the regional invasive list and blocks both checkout and swap intake outright; `rarity_flag`, also defaulting to false, marks rare heirloom stock and adds a bonus to swap-credit valuation. New varieties begin with a `status` of `ACTIVE`. Catalog edits — to `variety_name`, either flag, `approved_zones`, or `status` — run under the optimistic-concurrency rule of §2.7: the request must carry `expected_seed_variety_version`, and a stale view is refused with `ERR_STALE_VERSION`. A variety moved to `RETIRED` blocks the creation of new lots, new checkouts, and new swap-intake items against it, with such attempts rejected as `ERR_INVALID_STATE`. The catalog list is readable by all three roles and filterable by `category` and `status`.

Physical seed arrives as a lot. Intake records the `variety_id` it belongs to, the `home_site_id` holding the physical stock, the supplier or donor `lot_code` used on packet labels, the `harvest_year` (accepted between 2000 and 2100 inclusive), the `seeds_received` count (at least 1), and the donor-declared `provisional_viability_pct` between 0.00 and 100.00 at two decimal places. The combination of variety, harvest year, and lot code must be unique; a collision is rejected with `ERR_DUPLICATE_LOT_CODE`. A new lot begins in `DRAFT` with `seeds_remaining` — the loose-seed bucket — equal to the received count, `seeds_in_packets` and `seeds_discarded` at zero, `packets_created_total` at zero, and `final_viability_pct` null — viability is provisional until a certified assay exists.

Submitting a lot for review moves it from `DRAFT` to `QUARANTINE` and requires `seeds_remaining` to be greater than zero; an empty lot cannot enter quarantine and the attempt draws `ERR_INVALID_STATE`. A lot already in circulation can be sent back through the same door: the scheduled re-test loop moves an `ACTIVE` lot to `QUARANTINE` so a fresh assay can be recorded. Retirement closes the other end — an `ACTIVE` lot may be patched to `RETIRED` only while none of its packets is `CHECKED_OUT`; on retirement every still-`AVAILABLE` packet of the lot becomes `DISCARDED` and those seeds move from the in-packets bucket into the discarded bucket. Finally, the system watches for exhaustion: after every pack or packet-void mutation on an `ACTIVE` lot, if no loose seeds remain and no packet of the lot is still `AVAILABLE`, the lot transitions itself to `DEPLETED`. `DEPLETED`, `REJECTED`, and `RETIRED` are terminal, and any further mutation trigger against them is refused with `ERR_ALREADY_TERMINAL`. The lot list is filterable by `variety_id`, `home_site_id`, and `status`.

### 3.3. Germination Assays, Certification, and the Recall Cascade

While a lot sits in `QUARANTINE`, an `ACTIVE` volunteer records a germination assay against it, supplying `seeds_tested` (at least 1) and `sprouted_count` (at least 0 and never more than `seeds_tested`; shape violations draw `ERR_INVALID_REQUEST`). Recording against a lot in any other state is refused with `ERR_INVALID_STATE`. The system computes `result_pct` as the sprouted share of the tested seeds expressed as a percentage — sprouted divided by tested, multiplied by one hundred — rounded half up to two decimal places, and stamps the assay's `recorded_by_volunteer_id` from the caller's `X-User-ID`. Every assay begins `RECORDED`; the test list is filterable by `lot_id`, `recorded_by_volunteer_id`, and `status`.

Certification belongs exclusively to `ProgramAdmin` — a deliberate segregation of duties: the volunteer who recorded an assay can never certify it, because recording and certification sit in different roles. Certifying a test that is not `RECORDED` is refused with `ERR_TEST_NOT_RECORDED`, while certifying one already in the terminal `CERTIFIED` or `VOIDED` state falls under terminal lockdown with `ERR_ALREADY_TERMINAL`. The declared `outcome` must agree with the measured band: `PASS` requires a `result_pct` of at least 70.00, and `FAIL` requires one strictly below 70.00; disagreement is rejected with `ERR_VIABILITY_OUTCOME_MISMATCH`. A certified test becomes `CERTIFIED`, and its consequences unfold on the lot in three distinct branches, each fully specified:

- A `PASS` on a quarantined lot activates it: the lot moves `QUARANTINE` → `ACTIVE`, its `final_viability_pct` takes the test's `result_pct`, and its `viable_seed_count` is recomputed from the loose-seed count against that certified figure.
- A `FAIL` on a lot that has never circulated — no packets ever created — condemns it: the lot moves `QUARANTINE` → `REJECTED`, terminal.
- A `FAIL` on a lot that has already circulated packets (a post-recheck failure) triggers the recall cascade. Hop one: every packet of the lot in `AVAILABLE`, `CHECKED_OUT`, or `RETURNED` becomes `RECALLED`, each packet's `version` advancing. Hop two: every checkout holding a recalled packet while itself in `ACTIVE` or `OVERDUE` has its `recall_required` flag set true, each such checkout's `version` advancing. Hop three: the members holding those flagged checkouts are counted by the next daily sweep — the cascade performs no immediate member mutation; standing is recomputed only when the sweep runs. The lot itself returns to `QUARANTINE` and may be tested again.

When a recorded assay turns out to be a data-entry error, an administrator voids it: `RECORDED` → `VOIDED`, terminal. Voided tests are excluded everywhere viability is read; a lot's `final_viability_pct` always reflects the most recently certified assay in certification order.

The effective viability of a lot — the figure behind every viability-dependent decision — is the `final_viability_pct` when at least one certified assay exists, and the donor-declared `provisional_viability_pct` otherwise. The lot's `viable_seed_count` is the loose-seed count multiplied by that effective percentage, divided by one hundred, and rounded down to a whole seed; it is recomputed whenever the loose count changes, whenever a test is certified, and on every read of the lot.

### 3.4. Packing Operations and Packet Disposition

Packing converts loose seed into labeled packets, and it is volunteer work: an `ACTIVE` volunteer packs from an `ACTIVE` lot — any other lot state is refused with `ERR_LOT_NOT_ACTIVE` — by naming a `packet_count` and a `seeds_per_packet`. Three independent ceilings cap what may be packed in one request. The seed ceiling is the lot's `viable_seed_count` divided by `seeds_per_packet`, rounded down. The label ceiling is the home site's `label_stock_count`, one label per packet. The lifetime ceiling is two hundred packets per lot minus the lot's `packets_created_total` so far. The allocatable quantity is the smallest of the three; a request is admitted only when `packet_count` is at least 1 and at most that allocatable figure, and is otherwise rejected with `ERR_PACK_QUANTITY_EXCEEDS_ALLOCATABLE`.

A successful pack moves seeds and labels atomically: the lot's loose bucket decreases by `packet_count` times `seeds_per_packet` and its in-packets bucket increases by the same amount; the site's `label_stock_count` falls by `packet_count`; the lot's `packets_created_total` rises by `packet_count`. Both the lot and the site advance their `version`. New packets begin `AVAILABLE`, each stamped with a human-readable `packet_code` built from the lot code, the harvest year, and a three-digit per-lot sequence that starts at 001 — for example, the first packet of lot "BRN-24" harvested in 2024 reads "BRN-24-2024-001". The response reports `created_count`, the `lot_id`, and the `packet_ids` created, and the depletion auto-check of §3.2 runs immediately afterward. Packets are listable by `lot_id` and `status`.

Packets leave `AVAILABLE` in three ways beyond borrowing. An administrator may void an `AVAILABLE` packet — unpacking it — with a `mode` of `REINTEGRATE` or `DISCARD`: reintegration returns the packet's `seeds_count` to the lot's loose bucket, while discarding moves it into the discarded bucket, and in both modes the `seeds_count` leaves the in-packets bucket, the packet becomes `VOIDED`, the lot and packet versions advance, and the depletion check runs. Disposal is the recall exit: a `RECALLED` packet may be disposed of only once no checkout referencing it remains in `ACTIVE`, `OVERDUE`, `RETURNED`, or `DISPUTED`; disposal moves its `seeds_count` from the in-packets bucket to the discarded bucket and leaves the packet `DISCARDED`. The third exit is retirement, described in §3.2, which discards `AVAILABLE` packets wholesale. `VOIDED` and `DISCARDED` are terminal packet states; `RECALLED` packets can never return to circulation.

### 3.5. Borrowing, Returns, Disputes, and the Daily Sweep

Borrowing is the member-facing heart of the program. A member creates a checkout for themselves — or an administrator creates one on any member's behalf — by supplying a `member_id` and a `packet_id`. The creation pipeline evaluates its guards in a fixed order, and the first failure is the answer. The packet must be `AVAILABLE` (`ERR_PACKET_NOT_AVAILABLE`). The borrowing member must be `ACTIVE` — a `SUSPENDED` or `CLOSED` member is refused with `ERR_MEMBER_SUSPENDED`. The packet's lot must be `ACTIVE`, else `ERR_LOT_NOT_ACTIVE`; a variety retired behind the lot likewise blocks creation under the generic state rule. The variety's `invasive_flag` must be false, else `ERR_INVASIVE_SPECIES_BLOCKED`. The variety's `approved_zones` must contain the region zone of the member's home site, else `ERR_REGION_NOT_APPROVED`. The member's borrow limit must admit one more checkout, else `ERR_BORROW_LIMIT_EXCEEDED`. Only then does the ownership rule of §2.1 apply, refusing a member who named someone else's `member_id` with `ERR_SELF_SERVICE_FORBIDDEN`.

The borrow limit deserves its own paragraph because its evaluation order is pinned to break an apparent circle — the limit depends on the tier, the tier depends on the rate, and the rate depends on checkout outcomes, but the in-flight attempt never participates. First, the member's `simple_return_rate` is computed over terminal checkouts only — those in `VERIFIED` or `WRITTEN_OFF` — as the verified share of that terminal set, or 0.0 when the member has no terminal checkouts yet; `ACTIVE`, `OVERDUE`, `RETURNED`, and `DISPUTED` checkouts are excluded from both the numerator and the denominator. Second, the `standing_tier` is derived: `TRUSTED` when the member has at least five terminal checkouts and a rate of at least 0.90; `PROBATION` when the member has at least three terminal checkouts and a rate below 0.60; `STANDARD` otherwise, which covers every member with fewer than three terminal checkouts as unrated. Third, the tier maps to the `effective_borrow_limit`: 2 for `PROBATION`, 5 for `STANDARD`, 8 for `TRUSTED`. Finally, the attempt is admitted only while the member's `active_checkout_count` is strictly below that limit — sitting exactly at the limit is a rejection. The `active_checkout_count` itself counts the member's non-terminal checkouts, meaning those in `ACTIVE`, `OVERDUE`, `RETURNED`, or `DISPUTED`.

A created checkout starts `ACTIVE` with `checked_out_at` stamped from the logical clock and `due_at` exactly twenty-one days later. The packet moves `AVAILABLE` → `CHECKED_OUT`, the member's `active_checkout_count` rises by one, and both the member's and the packet's `version` advance. Checkout records also carry `returned_at` — null until a return is recorded — and the `recall_required` flag, which only the recall cascade of §3.3 sets. The checkout list is filterable by `member_id`, `packet_id`, and `status`.

Returns run a two-step pipeline. Recording the return moves an `ACTIVE` or `OVERDUE` checkout to `RETURNED`, stamps `returned_at` from the logical clock, and moves its packet `CHECKED_OUT` → `RETURNED`; a member may record only their own returns. Verification is staff work: an administrator verifies a `RETURNED` checkout into the terminal `VERIFIED` state, and the packet's fate depends on its lot — when the lot is `ACTIVE` the packet returns to `AVAILABLE` for the next borrower, and when the lot is no longer `ACTIVE` the packet is instead `DISCARDED`, its seeds moving from the in-packets bucket to the discarded bucket. Verification recomputes the member's counters: the terminal count rises by one, the verified count rises by one, and the overdue count falls by one when the checkout had previously been flipped overdue. The member's rates, tier, and limit are recomputed from the new history, and a suspended member whose overdue count has fallen to two or fewer is automatically reinstated to `ACTIVE`. The checkout, the packet, and the member all advance their `version`.

Disputes provide the escape valve. From `RETURNED`, an administrator opens a dispute — the inspection failed, the packet came back damaged — moving the checkout to `DISPUTED`. From `OVERDUE`, either the owning member or an administrator may open it, optionally attaching a `reason`. Resolution is administrator-only and takes an `outcome`: `RETURN_ACCEPTED` loops the checkout back to `RETURNED` so verification can proceed normally, while `WRITE_OFF` terminates it as `WRITTEN_OFF` and runs the write-off cascade — the held packet, whether `CHECKED_OUT` or `RETURNED`, becomes `DISCARDED` with its seeds moving to the discarded bucket; the member's terminal count rises by one, the overdue count falls by one when it had been flipped, rates and tier are recomputed, and the same auto-reinstatement check applies; the checkout, packet, member, and lot all advance their `version`.

Aging is driven by the daily sweep, an administrator-triggered ops-run checkpoint that executes in two ordered passes. Pass one walks every `ACTIVE` checkout ordered by `due_at` ascending with ties broken by `created_at` ascending, and flips each one whose `due_at` is strictly before the current logical time to `OVERDUE` — a checkout due exactly now stays `ACTIVE` — incrementing the owning member's `overdue_checkout_count` as it goes. Pass two walks every `ACTIVE` member in `created_at` ascending order and suspends each whose overdue count has reached three: exactly three overdue checkouts suspends, two does not. The sweep never reinstates anyone — reinstatement happens only on verify-return and write-off transitions — and it reports `overdue_flipped_count`, `members_suspended_count`, and a `members_reinstated_count` that is always zero. Suspension moves a member `ACTIVE` → `SUSPENDED`, blocking further member-initiated borrowing until enough returns or resolutions bring the overdue count back down.

Alongside the simple rate, the system maintains each member's `decay_weighted_return_score`, a recency-weighted participation metric surfaced on member reads. Over the same terminal set, each checkout contributes an outcome of 1 for `VERIFIED` and 0 for `WRITTEN_OFF`, multiplied by a weight that decays with age: the elapsed time between the checkout's `due_at` and the current logical time, expressed in days by dividing its seconds by 86,400 and floored at zero for checkouts that closed before their due date, is divided by a ninety-day half-life, and the weight is one-half raised to that power. The score is the sum of weighted outcomes divided by the sum of weights — 0.0 when the terminal set is empty — held at four decimal places, rounded half up.

### 3.6. Swap Events and the Credit Economy

Swap events are the program's other half: scheduled gatherings where members bring seed packets, plant starts, and cuttings, and leave with credit. Creating an event takes the hosting `site_id`, a `title`, and a `start_at`/`end_at` pair with the end strictly after the start; the event begins in `DRAFT`. Because a branch can host only one swap at a time, events at the same site observe a buffered-overlap rule: each event claims an interval from thirty minutes before its start until thirty minutes after its end, and that buffered interval must not intersect any other non-`CANCELLED` event's buffered interval at the same site. The check is half-open — one event's buffered end landing exactly on another's buffered start is permitted — and violations are rejected with `ERR_EVENT_WINDOW_OVERLAP`. The check runs at creation, again at publish, and again on any reschedule that moves the times.

The lifecycle then walks a fixed corridor. Publishing moves `DRAFT` → `SCHEDULED` with the overlap check re-run. Opening intake moves `SCHEDULED` → `INTAKE_OPEN` and requires the hosting site itself to be `ACTIVE`, else `ERR_INVALID_STATE`. While an event sits in `DRAFT` or `SCHEDULED`, an administrator may still rename or reschedule it under the optimistic-concurrency rule — the request carries `expected_swap_event_version`, a stale view draws `ERR_STALE_VERSION`, and any change to the times re-runs the overlap check; events past those states refuse the edit with `ERR_INVALID_STATE`, and terminal events with `ERR_ALREADY_TERMINAL`.

Members submit contributions while intake is open — one item per call — naming the `member_id`, the `variety_id`, an `item_type` of `SEED_PACKET`, `PLANT_START`, or `CUTTING`, and an assessed `condition` of `EXCELLENT`, `GOOD`, or `FAIR`. Submission against an event that is not `INTAKE_OPEN` is refused with `ERR_EVENT_NOT_INTAKE_OPEN`. The safety screens run next, in order: an invasive variety is refused with `ERR_INVASIVE_SPECIES_BLOCKED`, and a variety whose `approved_zones` does not contain the event site's `region_zone` is refused with `ERR_REGION_NOT_APPROVED`. A duplicate check follows: the same member submitting the same item type of the same variety at the same event is rejected with `ERR_DUPLICATE_INTAKE_ITEM` while a non-terminal twin — one still `SUBMITTED` or `ACCEPTED` — exists. Each accepted-as-submitted item carries a computed `credit_value` whose rounding order is pinned per item, never sum-then-round: the base value for its type — 2 for a seed packet, 5 for a plant start, 3 for a cutting — is multiplied by its condition factor — one and a half for `EXCELLENT`, exactly one for `GOOD`, one half for `FAIR` — and the product is rounded half up to a whole credit; a variety flagged rare adds a flat 2-credit bonus on top.

Before the submission is stored, the event credit cap applies to the request as a whole: the member's credits already earned at this event plus the submission's total must not exceed 25. Reaching exactly 25 is allowed; exceeding it rejects the entire submission with `ERR_EVENT_CREDIT_CAP_EXCEEDED` — there is no partial acceptance. A stored item begins `SUBMITTED`, and the intake-item list is filterable by `event_id`, `member_id`, `variety_id`, and `status`.

Screening is administrator judgment. While the event is `INTAKE_OPEN`, an administrator screens a `SUBMITTED` item with an `outcome` of `ACCEPT` or `REJECT`; rejection is also permitted while the event is `INTAKE_CLOSED`, so leftover items can still be dispositioned after the doors close. Acceptance moves the item to `ACCEPTED` and immediately pays for it: a `CreditEntry` of type `EARNED` for the item's `credit_value` is appended against the member and scoped to the event, with a system-generated provenance `note`, and the member's earned total and balance are recomputed. Rejection simply moves the item to `REJECTED`. A member may also withdraw their own still-`SUBMITTED` item, moving it to `WITHDRAWN`; administrators may withdraw on a member's behalf.

Credits are spent at the event itself. While the event is `INTAKE_OPEN`, a member redeems by naming `member_id` and a positive `credits` amount; redemption against a closed or unopened event draws `ERR_EVENT_NOT_INTAKE_OPEN`. Three ceilings bind the amount, all enforced under `ERR_INSUFFICIENT_CREDITS`: the amount must be at least 1, must not exceed the member's overall `credits_balance`, and must not exceed the event-scoped remainder — the credits the member has earned at this event minus those already redeemed at this event. A valid redemption appends a `REDEEMED` entry, recomputes the member's totals, and answers with the `member_id`, the `credits_redeemed` count, and the resulting `credits_balance`.

Three exits close the event, each with its own cascade. Closing intake moves `INTAKE_OPEN` → `INTAKE_CLOSED` and sweeps every still-unscreened `SUBMITTED` item into `REJECTED`. Completion moves `INTAKE_CLOSED` → `COMPLETED`, flips every `ACCEPTED` item to `SWAPPED`, and expires the event's unredeemed credit: for each member with earnings scoped to the event, the expired increment is the earned-at-event total minus the redeemed-at-event total, floored at zero, and a positive increment is appended as an `EXPIRED` entry with the member's totals recomputed. Cancellation is permitted from `SCHEDULED` or `INTAKE_OPEN` only and is forbidden outright — with `ERR_EVENT_NOT_CANCELLABLE` — once any `REDEEMED` entry exists for the event, because spent credit cannot be unspent. The cancel cascade then runs in two hops: hop one moves every `SUBMITTED` or `ACCEPTED` item to `RETURNED_TO_OWNER`, and hop two, caused by each accepted item's return, appends a `REVOKED` entry for each member equal to everything they earned at the event, recomputing `credits_revoked_total` and `credits_balance`. `REJECTED`, `WITHDRAWN`, `RETURNED_TO_OWNER`, and `SWAPPED` are the terminal item states; `COMPLETED` and `CANCELLED` are the terminal event states.

The credit ledger is readable but never writable from outside: entries carry the `member_id`, the scoping `event_id`, an `entry_type` of `EARNED`, `REDEEMED`, `EXPIRED`, or `REVOKED`, a positive integer `credits` amount, and the provenance `note`. The entry list is filterable by `member_id`, `event_id`, and `entry_type`. A member's credit summary — `credits_earned_total`, `credits_redeemed_total`, `credits_expired_total`, `credits_revoked_total`, and `credits_balance` — is a computed read over that ledger, and the conservation invariant of §2.10 holds across every append: what was earned always equals what was redeemed, expired, revoked, and still outstanding.

### 3.7. Packing Sessions and Volunteer Rosters

The program staffs its packing work through scheduled sessions. Creating one takes the `site_id`, a `title`, a `start_at`/`end_at` pair with the end strictly after the start, and a `capacity` of at least 1 — the maximum number of volunteers holding a live assignment. Sessions at the same site observe a half-open overlap rule: a new session's interval from start to end must not intersect any non-`CANCELLED` session's interval at that site, though back-to-back scheduling — one session's end landing exactly on another's start — is allowed. Violations are rejected with `ERR_SESSION_WINDOW_OVERLAP`. A new session begins `SCHEDULED`, and the session list is filterable by `site_id` and `status`.

Sign-up joins a volunteer to a session, with the `volunteer_id` naming who — a volunteer names only themselves, while an administrator may roster anyone. The volunteer must be `ACTIVE`, and the session must still be `SCHEDULED`; sign-up against a session that has reached a terminal state falls under terminal lockdown with `ERR_ALREADY_TERMINAL`. Two further checks guard the roster, evaluated in this order: the double-booking screen first, capacity second. Double-booking uses closed-interval semantics across the volunteer's live assignments — those in `SIGNUP` or `ATTENDED`: sessions that merely touch, one ending exactly when the next begins, still count as a conflict because volunteers have zero travel time, and any overlap or touch is rejected with `ERR_VOLUNTEER_DOUBLE_BOOKED`. Capacity then requires the session's live-assignment count to remain strictly below `capacity`; a session already full rejects the sign-up with `ERR_SESSION_CAPACITY_FULL`. A successful sign-up creates the assignment in `SIGNUP`, and the assignment list is filterable by `session_id`, `volunteer_id`, and `status`.

Two assignment transitions are manual. The owning volunteer — or an administrator — cancels a `SIGNUP` assignment, moving it to `CANCELLED`. An administrator marks a `SIGNUP` assignment `ATTENDED`, which remains possible while the session is `SCHEDULED` and even after it has been `COMPLETED`, so attendance can be trued up after the fact. Two more arrive by cascade from the session: completing a session — allowed only once the logical clock has reached its `end_at`, else `ERR_INVALID_STATE` — moves it `SCHEDULED` → `COMPLETED` and flips every assignment still in `SIGNUP` to `NO_SHOW`; cancelling a session moves it `SCHEDULED` → `CANCELLED` and flips those same assignments to `CANCELLED`. `ATTENDED`, `NO_SHOW`, and `CANCELLED` are the terminal assignment states, and like every terminal state in the system they refuse further mutation with `ERR_ALREADY_TERMINAL`.

## 4. Endpoint Definitions

All endpoints live under the `/api` prefix. Creating a new resource returns HTTP 201; modifications, lifecycle actions, and reads return HTTP 200. The table below is a contract index only — request payloads, computed fields, and side effects are defined by the narratives of §2 and §3.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /api/_clock/set_current_utc | Set the logical clock to a supplied instant (test-driving). | ProgramAdmin |
| POST | /api/ops/run-daily-sweep | Run the overdue flip pass followed by the suspension sweep. | ProgramAdmin |
| POST | /api/sites | Register a library branch or partner garden site. | ProgramAdmin |
| GET | /api/sites | List sites, paginated; filterable by status. | ProgramAdmin, Member, Volunteer |
| GET | /api/sites/{id} | Fetch one site. | ProgramAdmin, Member, Volunteer |
| PATCH | /api/sites/{id} | Update site metadata or toggle ACTIVE/INACTIVE. | ProgramAdmin |
| POST | /api/members | Register a member at a home site. | ProgramAdmin |
| GET | /api/members | List members, paginated; filterable by home site and status. | ProgramAdmin |
| GET | /api/members/{id} | Fetch one member; Member role reads only its own record. | ProgramAdmin, Member |
| PATCH | /api/members/{id} | Update member profile or close the membership. | ProgramAdmin |
| GET | /api/members/{id}/credit-summary | Computed read of the member's credit ledger totals; self-only for Member. | ProgramAdmin, Member |
| POST | /api/volunteers | Register a volunteer, starting APPLIED. | ProgramAdmin |
| GET | /api/volunteers/{id} | Fetch one volunteer. | ProgramAdmin, Volunteer |
| POST | /api/volunteers/{id}/approve | Approve a volunteer from APPLIED to ACTIVE. | ProgramAdmin |
| PATCH | /api/volunteers/{id} | Update volunteer profile or toggle ACTIVE/INACTIVE. | ProgramAdmin |
| POST | /api/seed-varieties | Create a catalog variety with flags and approved zones. | ProgramAdmin |
| GET | /api/seed-varieties | List varieties, paginated; filterable by category and status. | ProgramAdmin, Member, Volunteer |
| GET | /api/seed-varieties/{id} | Fetch one variety. | ProgramAdmin, Member, Volunteer |
| PATCH | /api/seed-varieties/{id} | Edit variety metadata; OCC-guarded, stale views rejected with 412. | ProgramAdmin |
| POST | /api/seed-lots | Intake a seed lot, starting DRAFT with loose seeds equal to seeds received. | ProgramAdmin |
| GET | /api/seed-lots | List lots, paginated; filterable by variety, home site, and status. | ProgramAdmin, Member, Volunteer |
| GET | /api/seed-lots/{id} | Fetch one lot. | ProgramAdmin, Member, Volunteer |
| PATCH | /api/seed-lots/{id} | Retire an ACTIVE lot, discarding its available packets. | ProgramAdmin |
| POST | /api/seed-lots/{id}/submit-for-review | Move a lot from DRAFT to QUARANTINE for germination testing. | ProgramAdmin |
| POST | /api/seed-lots/{id}/recheck | Move an ACTIVE lot back to QUARANTINE for a scheduled re-test. | ProgramAdmin |
| POST | /api/seed-lots/{id}/germination-tests | Record a germination assay for a QUARANTINE lot. | Volunteer |
| GET | /api/germination-tests | List germination tests, paginated; filterable by lot, recording volunteer, and status. | ProgramAdmin, Member, Volunteer |
| GET | /api/germination-tests/{id} | Fetch one germination test. | ProgramAdmin, Member, Volunteer |
| POST | /api/germination-tests/{id}/certify | Certify a RECORDED test with outcome PASS or FAIL. | ProgramAdmin |
| POST | /api/germination-tests/{id}/void | Void a RECORDED test recorded in error. | ProgramAdmin |
| POST | /api/seed-lots/{id}/pack | Pack packets from an ACTIVE lot under the allocation ceilings. | Volunteer |
| GET | /api/seed-packets | List packets, paginated; filterable by lot and status. | ProgramAdmin, Member, Volunteer |
| GET | /api/seed-packets/{id} | Fetch one packet. | ProgramAdmin, Member, Volunteer |
| POST | /api/seed-packets/{id}/void | Void an AVAILABLE packet, reintegrating or discarding its seeds. | ProgramAdmin |
| POST | /api/seed-packets/{id}/dispose | Dispose of a RECALLED packet once no live checkout holds it. | ProgramAdmin |
| POST | /api/checkouts | Borrow a packet; Member role borrows only for itself. | Member, ProgramAdmin |
| GET | /api/checkouts | List checkouts, paginated; filterable by member, packet, and status. | ProgramAdmin, Member, Volunteer |
| GET | /api/checkouts/{id} | Fetch one checkout. | ProgramAdmin, Member, Volunteer |
| POST | /api/checkouts/{id}/return | Record a return from ACTIVE or OVERDUE to RETURNED. | Member, ProgramAdmin |
| POST | /api/checkouts/{id}/verify-return | Verify a RETURNED checkout into VERIFIED; packet reintegrates or is discarded. | ProgramAdmin |
| POST | /api/checkouts/{id}/dispute | Open a dispute from RETURNED or OVERDUE. | Member, ProgramAdmin |
| POST | /api/checkouts/{id}/resolve-dispute | Resolve a dispute: accept the return or write the checkout off. | ProgramAdmin |
| POST | /api/swap-events | Create a swap event in DRAFT. | ProgramAdmin |
| GET | /api/swap-events | List swap events, paginated; filterable by site and status. | ProgramAdmin, Member, Volunteer |
| GET | /api/swap-events/{id} | Fetch one swap event. | ProgramAdmin, Member, Volunteer |
| PATCH | /api/swap-events/{id} | Reschedule or rename an event; OCC-guarded, DRAFT or SCHEDULED only. | ProgramAdmin |
| POST | /api/swap-events/{id}/publish | Publish an event from DRAFT to SCHEDULED. | ProgramAdmin |
| POST | /api/swap-events/{id}/open-intake | Open intake from SCHEDULED to INTAKE_OPEN. | ProgramAdmin |
| POST | /api/swap-events/{id}/close-intake | Close intake; unscreened submitted items are auto-rejected. | ProgramAdmin |
| POST | /api/swap-events/{id}/complete | Complete the event; accepted items swap and unredeemed event credits expire. | ProgramAdmin |
| POST | /api/swap-events/{id}/cancel | Cancel from SCHEDULED or INTAKE_OPEN; items return to owners and earned credits are revoked. | ProgramAdmin |
| POST | /api/swap-events/{id}/redeem-credits | Redeem event-scoped swap credits while intake is open. | Member, ProgramAdmin |
| POST | /api/swap-events/{id}/intake-items | Submit one item to an INTAKE_OPEN event. | Member, ProgramAdmin |
| GET | /api/intake-items | List intake items, paginated; filterable by event, member, variety, and status. | ProgramAdmin, Member, Volunteer |
| GET | /api/intake-items/{id} | Fetch one intake item. | ProgramAdmin, Member, Volunteer |
| POST | /api/intake-items/{id}/screen | Screen a SUBMITTED item, accepting or rejecting it. | ProgramAdmin |
| POST | /api/intake-items/{id}/withdraw | Withdraw a SUBMITTED item. | Member, ProgramAdmin |
| GET | /api/credit-entries | List credit ledger entries, paginated and append-only; filterable by member, event, and entry type. | ProgramAdmin, Member, Volunteer |
| GET | /api/credit-entries/{id} | Fetch one credit entry. | ProgramAdmin, Member, Volunteer |
| POST | /api/packing-sessions | Schedule a volunteer packing session. | ProgramAdmin |
| GET | /api/packing-sessions | List packing sessions, paginated; filterable by site and status. | ProgramAdmin, Member, Volunteer |
| GET | /api/packing-sessions/{id} | Fetch one packing session. | ProgramAdmin, Member, Volunteer |
| POST | /api/packing-sessions/{id}/cancel | Cancel a SCHEDULED session; sign-up assignments cascade to cancelled. | ProgramAdmin |
| POST | /api/packing-sessions/{id}/complete | Complete a SCHEDULED session once its end time has passed; remaining sign-ups become no-shows. | ProgramAdmin |
| POST | /api/packing-sessions/{id}/assignments | Sign a volunteer up for a session. | Volunteer, ProgramAdmin |
| GET | /api/packing-assignments | List packing assignments, paginated; filterable by session, volunteer, and status. | ProgramAdmin, Member, Volunteer |
| GET | /api/packing-assignments/{id} | Fetch one packing assignment. | ProgramAdmin, Member, Volunteer |
| POST | /api/packing-assignments/{id}/cancel | Cancel a SIGNUP assignment. | Volunteer, ProgramAdmin |
| POST | /api/packing-assignments/{id}/mark-attended | Mark a SIGNUP assignment as attended. | ProgramAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error are defined in §2 and §3; this table is the index of identifiers to HTTP status codes.

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_UNAUTHORIZED_ROLE | 403 |
| ERR_SELF_SERVICE_FORBIDDEN | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_REQUEST | 400 |
| ERR_INVALID_ENUM | 400 |
| ERR_INVALID_STATE | 409 |
| ERR_ALREADY_TERMINAL | 409 |
| ERR_MEMBER_SUSPENDED | 409 |
| ERR_LOT_NOT_ACTIVE | 409 |
| ERR_EVENT_NOT_INTAKE_OPEN | 409 |
| ERR_EVENT_NOT_CANCELLABLE | 409 |
| ERR_TEST_NOT_RECORDED | 409 |
| ERR_VIABILITY_OUTCOME_MISMATCH | 422 |
| ERR_INVASIVE_SPECIES_BLOCKED | 422 |
| ERR_REGION_NOT_APPROVED | 422 |
| ERR_PACKET_NOT_AVAILABLE | 409 |
| ERR_DUPLICATE_LOT_CODE | 409 |
| ERR_DUPLICATE_INTAKE_ITEM | 409 |
| ERR_EVENT_WINDOW_OVERLAP | 409 |
| ERR_SESSION_WINDOW_OVERLAP | 409 |
| ERR_VOLUNTEER_DOUBLE_BOOKED | 409 |
| ERR_SESSION_CAPACITY_FULL | 422 |
| ERR_BORROW_LIMIT_EXCEEDED | 422 |
| ERR_PACK_QUANTITY_EXCEEDS_ALLOCATABLE | 422 |
| ERR_EVENT_CREDIT_CAP_EXCEEDED | 422 |
| ERR_INSUFFICIENT_CREDITS | 422 |
| ERR_STALE_VERSION | 412 |
