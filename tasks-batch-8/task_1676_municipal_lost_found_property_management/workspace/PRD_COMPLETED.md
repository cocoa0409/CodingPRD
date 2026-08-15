# Municipal Lost & Found Property Management API — Product Requirements Document

## 1. Introduction

Every day, city transit vehicles, recreation centers, libraries, and municipal facilities accumulate found property — wallets, phones, bicycles, identification documents, and cash. Today these programs run on paper tags and spreadsheets: owners cannot discover their belongings online, retention deadlines are tracked by hand, handovers lack consistent documentation, and unclaimed-property auctions are assembled ad hoc with little auditability. Disputes over ownership, premature disposal of valuables, and mishandled identification documents create legal exposure for the city.

This document specifies the Municipal Lost & Found Property Management API, the backend for a unified city and transit lost-and-found operation. The API governs the full lifecycle of found property: intake and cataloguing with value-tier classification, storage management with capacity and secure-vault rules, a public searchable inventory, owner claim examination with a weighted proof-of-ownership score, documented release with strict segregation of duties, law-enforcement referral and evidence conversion, and the auction or disposal of unclaimed property with per-venue insurance caps and tiered commission settlement. Because transit programs promise faster turnaround than facility programs, retention and inquiry-response deadlines are computed per program type. The system serves nine distinct operator and public roles and enforces its rules through a single, deterministic validation order so that auditors can reconstruct exactly why any request was refused.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API are authenticated through two HTTP headers. Each request must carry `X-User-Role` naming one of the nine declared roles, and `X-User-ID` identifying the actor; `X-User-ID` is optional only when the role is `PublicUser` and required for every other role. A missing or unrecognized role header, or a missing `X-User-ID` for a non-`PublicUser` role, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). Access to each operation is restricted by role; an authenticated caller whose role is not authorized for the endpoint, or a `Claimant` attempting to act on another claimant's resource, is rejected with `ERR_FORBIDDEN` (HTTP 403).

The nine roles are:

- `PublicUser` — an unauthenticated-equivalent visitor of the online portal who may browse the public inventory, register as a claimant, and submit inquiries.
- `Claimant` — a registered owner claiming property; may only touch its own claims and its own claimant record.
- `IntakeOfficer` — front-desk staff registering and describing found property, publishing items to the public inventory, and answering public inquiries.
- `PropertyCustodian` — back-office custodian managing storage moves and disposal.
- `ClaimsExaminer` — reviews ownership claims, verifies claimant identification, and approves or rejects claims.
- `ReleaseOfficer` — performs the documented handover of property to verified owners.
- `PoliceLiaison` — interfaces with law enforcement for high-value, identification, and evidence items.
- `AuctionCoordinator` — runs auctions: events, lots, sales, and settlement.
- `ProgramAdmin` — city administrator owning programs, retention policies, storage locations, venues, the logical clock, and the retention sweep.

The meaning of `X-User-ID` differs by role. When `X-User-Role` is `Claimant`, `X-User-ID` is the `id` of the acting `Claimant` entity; ownership checks on any resource that references a `Claimant` compare the resource's `claimant_id` field to `X-User-ID`, and claim creation requires the payload's `claimant_id` to equal `X-User-ID`. When `X-User-Role` is `PublicUser`, `X-User-ID` is an opaque visitor identifier not tied to any persisted entity. When `X-User-Role` is any of `IntakeOfficer`, `PropertyCustodian`, `ClaimsExaminer`, `ReleaseOfficer`, `PoliceLiaison`, `AuctionCoordinator`, or `ProgramAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity: the server records it on resources it creates or mutates (for example as `intake_officer_id` on an item, `examiner_id` on a claim, `answered_by` on an inquiry, `referred_by` on a referral case, `created_by` and `finalized_by` on an auction lot, or `released_by` on a release record) and duty-segregation rules compare the acting `X-User-ID` against such recorded operator identifiers, but the identifier is never resolved against a persisted user entity.

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
- Client-supplied datetimes stored on resources (`found_at`, `starts_at`, `ends_at`) and the `current_utc` reported by the clock endpoint are echoed normalized to UTC: a value falling on a whole second is rendered at second precision, and a value carrying a fractional part is rendered with three fractional digits.
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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0. Query parameters are part of the request's shape: a non-integer or negative `offset`, a non-integer `limit` or one outside [1, 100], and a filter value outside its declared enum set are each rejected with `ERR_INVALID_REQUEST` (HTTP 400).

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order; resources created at the same logical-clock instant keep their creation order, the sort being stable.

Paginated and non-paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

All primary resources — programs, retention policies, storage locations, venues, claimants, items, claims, inquiries, auction events, auction lots, and referral cases — carry a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed upon any change to the resource's properties; at creation it equals `created_at`.
- `version` (integer): a system-managed integer that starts at 1 when the resource is created and increments by exactly one on every mutation of the resource, including mutations caused by cascaded side effects from operations on other resources.

Two resources are exceptions to this convention. A lot-item membership row carries only `id` and `created_at`; both `updated_at` and `version` are absent from it. A release record likewise carries only `id` and `created_at`, with no `updated_at` and no `version`, reflecting its append-only nature.

### 2.5. The Logical Clock and Time-Gated Rules

The server maintains a logical clock that is independent of wall-clock time. At startup, before any explicit adjustment, the logical clock reads exactly `2026-08-01T00:00:00Z`, and it never falls back to wall-clock time thereafter. A `ProgramAdmin` may set the clock through `POST /_clock/set_current_utc`, supplying the target instant in the `to_iso8601` field; the response reports the new value as `current_utc`, and all subsequent server behavior uses the new clock value. Any well-formed instant is accepted, including one earlier than the current value — the clock is not monotonic.

The logical clock drives every server-stamped timestamp — `created_at`, `updated_at`, `released_at`, and the `api_request_timestamp` of every response envelope, each rendered with three fractional digits — and every time-gated rule in this document: the retention sweep compares item deadlines against it, event settlement checks the event window against it, and inquiry response deadlines are measured from it. Tests and operators therefore control time explicitly rather than waiting for it to pass.

### 2.6. Optimistic Concurrency Control

Three write operations are guarded by optimistic concurrency control on a parent resource. Each requires a non-optional request field carrying the caller's last observed `version` of the parent; if that value does not match the parent's current `version` — because another writer has advanced the parent since the caller last read it — the request is rejected with the stated error and no change is applied.

- Filing a claim requires `expected_item_version` matching the claimed item's current `version`. A mismatch is rejected with `ERR_STALE_ITEM_VERSION` (HTTP 412), because the claimant's view of the item — its storage state, competing claims, and referral status — is stale and the claim must be re-based on a fresh read.
- Adding an item to an auction lot requires `expected_lot_version` matching the lot's current `version`. A mismatch is rejected with `ERR_STALE_LOT_VERSION` (HTTP 412), because the lot's composition and `minimum_bid_cents` have changed and the coordinator's insurance-cap reasoning is stale.
- Creating a retention policy requires `expected_program_version` matching the owning program's current `version`. A mismatch is rejected with `ERR_STALE_PROGRAM_VERSION` (HTTP 412), because the policy set the administrator reviewed is no longer current.

Endpoints not listed here do not accept a version field; the server performs no optimistic-concurrency check on them.

### 2.7. Validation Order and Error Precedence

Requests that fail basic shape — a missing required field, a malformed value, or an enum value outside the declared set — are rejected with `ERR_INVALID_REQUEST` (HTTP 400) before any ordered business check runs.

When a request is well-formed, the server evaluates its checks in a single deterministic order, and the earliest failing check determines the error returned:

1. Authentication — `ERR_UNAUTHENTICATED`.
2. Authorization and actor-ownership — `ERR_FORBIDDEN`, including the claimant-ownership rules of §2.1.
3. Path-parameter resolution, left to right — `ERR_NOT_FOUND` (see §2.8).
4. Existence of foreign keys referenced in the request body — `ERR_NOT_FOUND` (see §2.8).
5. Optimistic concurrency — `ERR_STALE_ITEM_VERSION`, `ERR_STALE_LOT_VERSION`, or `ERR_STALE_PROGRAM_VERSION` as applicable (§2.6).
6. Generic state admissibility — the target resource's current state must permit the requested transition, otherwise `ERR_INVALID_STATE` (HTTP 409). This applies to all action endpoints.
7. Endpoint-specific state guards, in the order relevant to each endpoint — `ERR_ITEM_NOT_CLAIMABLE` (claim filing against an item that is not `STORED` or `LISTED`), `ERR_ITEM_NOT_AUCTION_ELIGIBLE` (lot add-item against an item not in `AUCTION_ELIGIBLE`), `ERR_LOTS_NOT_FINAL` (event settlement while any lot is `DRAFT` or `PUBLISHED`).
8. Business-safety rules — `ERR_IDENTIFICATION_NOT_LISTABLE`, then `ERR_CLAIM_PROOF_INSUFFICIENT`, then `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).
9. Business constraints — `ERR_PROGRAM_INACTIVE`, `ERR_LOCATION_INACTIVE`, `ERR_LOCATION_NOT_EMPTY`, `ERR_STORAGE_CAPACITY_EXCEEDED`, `ERR_SECURE_STORAGE_REQUIRED`, `ERR_NO_RETENTION_POLICY`, `ERR_DISPOSAL_METHOD_MISMATCH`, `ERR_LOT_EMPTY`, in the relative order relevant to each endpoint as narrated in §3.
10. Temporal rules — `ERR_INVALID_TIME_WINDOW`, `ERR_VENUE_DOUBLE_BOOKED`, `ERR_EVENT_STILL_OPEN`.
11. Cross-program referential consistency — `ERR_CROSS_PROGRAM_REFERENCE`.
12. Fiscal rules — `ERR_INSURANCE_CAP_EXCEEDED`, then `ERR_BELOW_MINIMUM_BID`.

Within any single endpoint, §3 states the concrete ordering of whichever of these checks apply; the sequence there always respects the global precedence above.

### 2.8. Nested Resource Retrieval and Referential Existence

For any request whose path contains resource identifiers — for example a lot item addressed under its lot, or any action addressed by an entity id — the server resolves the identifiers sequentially from left to right. The request is rejected immediately with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not correspond to an existing resource; later segments are not examined.

Independently, any identifier referenced in a request body must resolve to an existing resource. This applies wherever a payload names a `program_id` (item intake, policy creation, storage-location creation, venue creation, event creation, inquiry submission), a `storage_location_id` (item intake and item move), an `item_id` (claim filing, inquiry submission, lot add-item), a `claimant_id` (claim filing), a `venue_id` (event creation), or an `event_id` (lot creation). An unresolvable body reference is rejected with `ERR_NOT_FOUND`, after path resolution and before any state or business check.

### 2.9. Storage Occupancy Accounting

Every storage location tracks a computed `occupied_slots` count: the number of items currently assigned to that location whose `status` is one of `STORED`, `LISTED`, `RELEASE_PENDING`, `REFERRED_TO_LE`, `AUCTION_ELIGIBLE`, `LOTTED`, or `DISPOSAL_PENDING`. An item in `IN_LE_CUSTODY` does not occupy a slot, nor does an item in any terminal state (`RELEASED`, `EVIDENCE`, `SOLD`, `DISPOSED`, `DONATED`). The count starts at zero and is recomputed whenever an item is created at the location, whenever an item is moved, and whenever an item's status transition enters or leaves the occupying set — so a pickup confirmation for law enforcement frees a slot, a return to custody re-occupies it, and a sale, release, disposal, or donation frees it.

Capacity is enforced against this live count: a location accepts an incoming item only while doing so keeps the occupied count at or below `capacity_slots`; a location whose occupied count already equals its capacity rejects further intake or moves with `ERR_STORAGE_CAPACITY_EXCEEDED` (HTTP 409).

### 2.10. Monetary Values and Rounding Discipline

All monetary quantities in the system are integer counts of cents: `declared_value_cents`, `insurance_cap_cents`, `floor_price_cents`, `minimum_bid_cents`, `hammer_price_cents`, `gross_proceeds_cents`, `total_commission_cents`, and `net_proceeds_cents`. No fractional cents are stored.

Rounding, where a rate is applied, uses the round-half-up method to whole cents, and the rounding order is pinned: each individual amount is rounded to whole cents first, and only then are the rounded amounts summed. This discipline applies to per-item floor prices in a lot and to per-lot commissions in an event settlement. Summing unrounded products and rounding the total is forbidden, because the two orders yield different results. All threshold comparisons — value-tier boundaries, proof-score thresholds, capacity checks — are exact integer comparisons with the inclusivity stated in the prose of §3.

## 3. Business Logic & Workflows

### 3.1. Programs, Retention Policies, Storage, and Venues

Everything in the system belongs to a program. A `ProgramAdmin` creates a program with a display `name`, a `program_type` of either `TRANSIT` or `FACILITY`, and a public `contact_email`; the new program's `active` flag starts as true. The program type is not cosmetic — it drives both the retention-deadline arithmetic of §3.2 and the inquiry response deadlines of §3.3. Deactivating a program sets `active` to false and bumps its version; an inactive program rejects new item intake and rejects publishing of its stored items with `ERR_PROGRAM_INACTIVE` (HTTP 409), while its existing inventory otherwise continues through the lifecycle.

Each program defines how long found property is held through retention policies keyed by the triple of `program_id`, `item_category`, and `value_tier`. A policy declares `retention_days` (an integer of at least 1) and a `disposal_method` of `AUCTION`, `DESTRUCTION`, or `DONATION`, which determines where an expired item routes. Creating a policy supersedes any currently active policy with the same key triple: the superseded policy's `active` flips to false and its version increments, and the parent program's version increments as well. Because policy creation rewrites the program's policy set, it is one of the three concurrency-guarded writes of §2.6 and carries `expected_program_version`. Policies may be listed with `program_id`, `item_category`, `value_tier`, and `active` filters; programs may be listed with `program_type` and `active` filters.

Storage locations belong to a program and carry a human `name` such as "Cage A / Shelf 3", a `capacity_slots` count of at least 1, and a `supports_high_value` flag marking secure vault space; `active` starts true. A location can be deactivated only while its `occupied_slots` count (§2.9) is zero — deactivating a non-empty location is rejected with `ERR_LOCATION_NOT_EMPTY` — and an inactive location cannot receive items, so intake or moves targeting one are rejected with `ERR_LOCATION_INACTIVE`. Location lists support `program_id` and `active` filters.

Venues are the auction houses and sale floors a program uses. A venue record holds a `name`, a street `address`, and an `insurance_cap_cents` value of zero or more: the maximum aggregate minimum-bid value the venue will insure for a single event. The cap is enforced lot by lot as items are added (§3.8); an addition that would push a lot's projected minimum bid above the cap is rejected with `ERR_INSURANCE_CAP_EXCEEDED`. Venue lists support the `program_id` filter.

### 3.2. Found-Property Intake and Cataloguing

An `IntakeOfficer` registers each piece of found property with its `program_id`, the `storage_location_id` of the bin it physically occupies, a `category`, the officer's estimated `declared_value_cents` (a non-negative integer), a public-safe `description`, the `found_at` instant (ISO 8601 UTC) and `found_location` where it was discovered, and an optional `external_ref` carrying the physical tag number. The category is one of `ELECTRONICS`, `JEWELRY`, `ID_DOCUMENT`, `KEYS`, `CLOTHING`, `BAG`, `WALLET`, `BICYCLE`, `CASH`, or `OTHER`. A client may send `value_tier`, but the server ignores any client-sent tier and always computes its own. The officer's `X-User-ID` is recorded as the item's `intake_officer_id`, and the new item begins life in `STORED` status with `unsold_count` at zero and `pending_disposal_method` unset. Staff can later browse the inventory with `program_id`, `storage_location_id`, `retention_policy_id`, `status`, `category`, and `value_tier` filters.

Two facts about the item are fixed at intake and never recomputed afterwards. First, `value_tier` derives from `declared_value_cents` by exact integer comparison: a declared value below 10,000 cents is `LOW`; a declared value of at least 10,000 cents but below 100,000 cents is `MID`; a declared value of 100,000 cents or more is `HIGH`. The boundaries are inclusive upward — exactly 10,000 cents is `MID`, exactly 100,000 cents is `HIGH`. Second, `is_identification` is true exactly when the category is `ID_DOCUMENT`; identification items can never appear in the public inventory.

The item's retention terms are also resolved once at intake. The server looks up the active retention policy matching the item's `program_id`, `category`, and computed `value_tier`; if no active policy exists for that triple, intake is refused with `ERR_NO_RETENTION_POLICY` (HTTP 422). The matched policy's id is stored as `retention_policy_id`, and the `retention_deadline` is computed from `found_at` and the policy's `retention_days` according to the owning program's type. For a `TRANSIT` program the arithmetic is hour-precise: the deadline is `found_at` plus `retention_days` times 24 hours, preserving the time of day. For a `FACILITY` program the arithmetic is calendar-based: the item is held for the remainder of the calendar day on which it was found plus `retention_days` full calendar days, and the deadline falls at 00:00:00 UTC on the following morning — equivalently, at the midnight boundary after the calendar date that is `retention_days` days after the found date, with the time-of-day of `found_at` discarded. Deadlines are ISO 8601 UTC instants at second precision.

Intake is guarded by a fixed chain of checks, evaluated in this order after the global precedence of §2.7: the owning program must be active (`ERR_PROGRAM_INACTIVE`), the target location must be active (`ERR_LOCATION_INACTIVE`), the location must have spare capacity per §2.9 (`ERR_STORAGE_CAPACITY_EXCEEDED`), a `HIGH`-tier item may only be placed in a location whose `supports_high_value` is true (`ERR_SECURE_STORAGE_REQUIRED`, HTTP 422), and a matching retention policy must exist as above. Successful intake recomputes the location's occupancy.

Once stored, an item can be made publicly searchable: publishing transitions `STORED` to `LISTED`, and unpublishing returns `LISTED` to `STORED`. Publishing enforces its checks in order — the item must currently be `STORED` (`ERR_INVALID_STATE` otherwise), it must not be an identification item (`ERR_IDENTIFICATION_NOT_LISTABLE`, HTTP 422), and its program must be active (`ERR_PROGRAM_INACTIVE`). Both transitions increment the item's version.

A `PropertyCustodian` moves an item between locations by supplying the destination `storage_location_id`. The move applies the same trio of location checks as intake, in the same order — destination active, destination capacity, and secure storage for `HIGH`-tier items — and then recomputes occupancy for both the source and destination locations. A move whose destination is the item's current location nets the item's own slot, if it occupies one there, out of the destination's occupied count before the capacity check, so re-assigning an item to its own location never consumes a second slot. The item's version increments.

Across the whole document an item's `status` takes one of thirteen values: `STORED`, `LISTED`, `RELEASE_PENDING`, `RELEASED`, `REFERRED_TO_LE`, `IN_LE_CUSTODY`, `EVIDENCE`, `AUCTION_ELIGIBLE`, `LOTTED`, `SOLD`, `DISPOSAL_PENDING`, `DISPOSED`, and `DONATED`, of which `RELEASED`, `EVIDENCE`, `SOLD`, `DISPOSED`, and `DONATED` are terminal.

### 3.3. The Public Portal: Searchable Inventory and Inquiries

The public inventory exposes only items that are currently `LISTED` and whose `is_identification` is false. Both `PublicUser` and `Claimant` callers may search it with `category`, `keyword`, and `program_id` filters; `keyword` is a case-insensitive substring match against the item's `description`. The public projection is deliberately narrow: each result carries only `id`, `category`, `description`, `found_at`, `found_location`, and `program_id` — never the storage location, the declared value, or any claimant data.

Anyone may submit an inquiry about a lost item or a program in general. The submission carries `contact_email`, a `subject` line, and the `message` body, plus an optional `item_id`, an optional `program_id`, or neither. Every inquiry starts in `OPEN` status, and the server computes its `sla_deadline` at creation from the resolved program context: when an `item_id` is present the item's program governs; otherwise a present `program_id` governs; otherwise there is no program context. A `TRANSIT` program sets the deadline 24 hours after creation; a `FACILITY` program — or no program context at all — sets it 72 hours after creation. Like the retention deadlines of §3.2, the `sla_deadline` is an ISO 8601 UTC instant at second precision. The inquiry record exposes the computed `sla_deadline`, and staff lists can be filtered by `item_id`, `program_id`, and `status`.

An `IntakeOfficer` answers an `OPEN` inquiry, which transitions it to `ANSWERED`, stores the response in `answer_text`, and records the officer's `X-User-ID` as `answered_by`. Closing is permitted from either `OPEN` or `ANSWERED` and moves the inquiry to `CLOSED`, its terminal state. Each of these transitions increments the inquiry's version.

### 3.4. Ownership Claims: Filing, Scoring, and Examination

Claimants begin as self-registered members of the public: a `PublicUser` registers with `full_name`, `email`, and an optional `phone`, producing a claimant record whose `id_verified` starts as false. A `ClaimsExaminer` later marks identification as verified, which sets `id_verified` to true, increments the claimant's version, and triggers a recomputation of the proof score on every one of that claimant's claims currently in `SUBMITTED`, `UNDER_REVIEW`, or `INFO_REQUESTED`, incrementing each affected claim's version. A claimant may read only its own record and its own claims; staff roles with claim visibility are `ClaimsExaminer`, `ReleaseOfficer`, `PoliceLiaison`, and `ProgramAdmin`, and the claims list accepts `item_id`, `claimant_id`, and `status` filters.

Filing a claim is the act of asserting ownership of one item. The payload names the `item_id`, the `claimant_id` (which must equal the caller's `X-User-ID`, else `ERR_FORBIDDEN`), and four proof inputs: the boolean flags `proof_serial` asserting knowledge of a serial number or unique marking, `proof_photo` supplying a photo of the claimant with the item, and `proof_receipt` supplying a purchase receipt, plus `proof_description_detail` rating the claimant's independent description as `BRIEF` or `DETAILED`. Filing is concurrency-guarded per §2.6 through `expected_item_version`, and that stale-version check is evaluated before the claimability check. The item must be in `STORED` or `LISTED` — a claim against an item in any other state is rejected with `ERR_ITEM_NOT_CLAIMABLE`. A successfully filed claim starts in `SUBMITTED`, its `proof_score` is computed, `examiner_id`, `decision_reason`, `pre_stay_status`, and `info_request_text` start unset, and filing itself increments the item's version by one — the claimant's next view of the item reflects that a claim now hangs on it.

The `proof_score` is a weighted integer. It adds 30 points when the claimant's `id_verified` is true, 30 points when `proof_serial` is asserted, 15 points when `proof_photo` is supplied, 15 points when `proof_description_detail` is `DETAILED`, and 10 points when `proof_receipt` is supplied, for a maximum of 100. It is computed at filing, recomputed at resubmission, and recomputed on identification verification as described above.

Examination proceeds as a small state machine. Starting review moves `SUBMITTED` to `UNDER_REVIEW` and records the acting examiner's `X-User-ID` in `examiner_id`. Requesting more information moves `UNDER_REVIEW` to `INFO_REQUESTED`, stores the supplied `info_request_text`, and may only be performed by the recording examiner — any other examiner is rejected with `ERR_FORBIDDEN`. Resubmission is the claimant's reply: the owning claimant moves `INFO_REQUESTED` back to `SUBMITTED`, replacing all four proof inputs with the resubmission payload, and the score is recomputed. Withdrawal moves a claim from `SUBMITTED` or `INFO_REQUESTED` to `WITHDRAWN` and is likewise restricted to the owning claimant.

Approval is the most heavily guarded action in the claims workflow, and its checks run in a fixed order: authorization and examiner-ownership first (`ERR_FORBIDDEN`), then state admissibility — the claim must be `UNDER_REVIEW` and the claimed item must be `STORED` or `LISTED` (`ERR_INVALID_STATE` otherwise) — then proof sufficiency, then duty segregation. Proof sufficiency requires the `proof_score` to meet the threshold of the item's `value_tier`: at least 40 for `LOW`, at least 60 for `MID`, and at least 80 for `HIGH`, where `HIGH` additionally requires the claimant's `id_verified` to be true; a shortfall is rejected with `ERR_CLAIM_PROOF_INSUFFICIENT` (HTTP 422). Segregation of duties forbids the approving examiner from being the same `X-User-ID` recorded as the item's `intake_officer_id` (`ERR_SEGREGATION_OF_DUTIES`, HTTP 403). An optional `decision_reason` may accompany the approval. On success the claim becomes `APPROVED`, the item cascades from `STORED` or `LISTED` to `RELEASE_PENDING` with its version incremented, and every other claim on the same item that is in `SUBMITTED`, `UNDER_REVIEW`, or `INFO_REQUESTED` is auto-rejected with its `decision_reason` set to `ITEM_AWARDED`, each such claim's version incrementing.

Rejection is the mirror: the recording examiner rejects an `UNDER_REVIEW` claim with a required `decision_reason` from the input, moving it to the terminal `REJECTED` state. A claim's full state vocabulary is `SUBMITTED`, `UNDER_REVIEW`, `INFO_REQUESTED`, `STAYED`, `APPROVED`, `REJECTED`, `WITHDRAWN`, and `RELEASED`, with `REJECTED`, `WITHDRAWN`, and `RELEASED` terminal.

### 3.5. Release and Handover Documentation

Once a claim is approved, physical handover is a separate act performed by a `ReleaseOfficer`, never implicitly by the examiner. The officer supplies the `handover_method` — `IN_PERSON` or `MAIL` — and an `id_document_ref` referencing the claimant identification inspected at handover. The item must be in `RELEASE_PENDING` (`ERR_INVALID_STATE` otherwise), and two segregation rules apply: the releasing officer's `X-User-ID` must differ from the item's `intake_officer_id`, and it must differ from the `examiner_id` of the approved claim on the item. Either collision is rejected with `ERR_SEGREGATION_OF_DUTIES`.

A successful release creates a release record capturing `item_id`, the `claim_id` of the approved claim it satisfies, `released_by` set to the officer's `X-User-ID`, the handover inputs, and `released_at` stamped from the logical clock. In the same operation the item moves from `RELEASE_PENDING` to `RELEASED`, the approved claim moves from `APPROVED` to `RELEASED`, the storage slot is freed per §2.9, and both the item's and the claim's versions increment; the operation answers 200 OK carrying the updated item. Release records are append-only documentation: staff may list them with `item_id` and `claim_id` filters or read them individually, and no endpoint modifies or deletes them.

### 3.6. Law-Enforcement Referrals and Evidence Conversion

Found property is sometimes evidence, and the system treats the evidence path as a first-class branch that suspends the ordinary claims workflow rather than deleting it. A `PoliceLiaison` refers an item in `STORED` or `LISTED` to law enforcement by supplying the `agency_name` and the agency's `case_number`. The referral creates a referral case in `REFERRED` status with the officer's `X-User-ID` recorded as `referred_by` and the `item_id` attached, answered with 201 Created; the item moves to `REFERRED_TO_LE`; and every claim on the item in `SUBMITTED`, `UNDER_REVIEW`, or `INFO_REQUESTED` is stayed — moved to `STAYED` with its previous status preserved in `pre_stay_status`, each claim's version incrementing. Referral lists support `item_id` and `status` filters.

When officers collect the property, pickup confirmation requires the referral to be `REFERRED` and the item `REFERRED_TO_LE`; the referral moves `REFERRED` to `IN_CUSTODY`, the item moves to `IN_LE_CUSTODY`, the storage slot is freed because `IN_LE_CUSTODY` does not occupy, and both records' versions increment.

Two endings exist for a held item, and they diverge deliberately. Returning the item requires the referral `IN_CUSTODY` and the item `IN_LE_CUSTODY`: the referral becomes `RETURNED`, the item goes back to `STORED` (re-occupying its slot), and each `STAYED` claim on the item resumes the exact status captured in its `pre_stay_status` — one of `SUBMITTED`, `UNDER_REVIEW`, or `INFO_REQUESTED` — clearing that field, with each restored claim's version incrementing. Converting the item to evidence, from the same `IN_CUSTODY` state, is terminal for the property lifecycle: the referral becomes `CONVERTED_TO_EVIDENCE`, the item becomes `EVIDENCE`, and every claim on the item in `SUBMITTED`, `UNDER_REVIEW`, `INFO_REQUESTED`, or `STAYED` is auto-rejected with its `decision_reason` set to `ITEM_EVIDENCE`, each version incrementing. A referral case's terminal states are exactly `RETURNED` and `CONVERTED_TO_EVIDENCE`.

### 3.7. Retention Expiry, the Sweep, and Disposal

Unclaimed property does not move itself; a `ProgramAdmin` runs the retention sweep through the ops endpoint, which examines every item in `STORED` or `LISTED` whose `retention_deadline` has been reached by the current logical clock. Each such item branches on the `disposal_method` of the policy recorded as its `retention_policy_id` at intake, even if that policy has since been superseded: where the method is `AUCTION` the item becomes `AUCTION_ELIGIBLE`; where it is `DESTRUCTION` or `DONATION` the item becomes `DISPOSAL_PENDING` and its `pending_disposal_method` is fixed to the policy's method. Every transitioned item's version increments, and the sweep reports `transitioned_count` together with the `transitioned_item_ids` so operators can reconcile the physical shelves. Items whose deadlines have not passed, and items in any other status, are untouched.

Disposal is performed by a `PropertyCustodian` on an item in `DISPOSAL_PENDING`, supplying a `method` input drawn from the same `AUCTION`/`DESTRUCTION`/`DONATION` vocabulary as retention policies. The supplied method must equal the item's `pending_disposal_method` — a mismatch is rejected with `ERR_DISPOSAL_METHOD_MISMATCH` (HTTP 422), and because `pending_disposal_method` is only ever `DESTRUCTION` or `DONATION`, supplying `AUCTION` always lands on this rejection rather than on a shape error — which prevents, for example, donating an item that was slated for destruction. A matching `DESTRUCTION` moves the item to `DISPOSED`; a matching `DONATION` moves it to `DONATED`. Either way the slot is freed and the item's version increments.

There is a second route into `DISPOSAL_PENDING` that has nothing to do with the calendar: an item that fails to sell at auction twice is escalated to destruction, with `pending_disposal_method` fixed to `DESTRUCTION`. That escalation belongs to the auction workflow of §3.8, but its endgame is the same disposal act described here.

### 3.8. Auctions: Events, Lots, Sales, and Settlement

An `AuctionCoordinator` schedules an auction event at a venue, supplying `venue_id`, `program_id`, a `name`, and the sale window `starts_at` to `ends_at`. Creation enforces three checks in order. The window must be well-formed: `ends_at` strictly after `starts_at`, else `ERR_INVALID_TIME_WINDOW`. The venue's calendar must be free: the new event's half-open window — from `starts_at` inclusive up to but not including `ends_at` — may not overlap any other `SCHEDULED` or `COMPLETED` event at the same venue, else `ERR_VENUE_DOUBLE_BOOKED`; adjacency is allowed, so an event may begin exactly when another ends or end exactly when another begins. The event's `program_id` must equal the venue's `program_id`, else `ERR_CROSS_PROGRAM_REFERENCE`. A new event is `SCHEDULED`, its three settlement figures start unset, and event lists accept `venue_id`, `program_id`, and `status` filters.

Lots are created under an event with the `event_id` and a `title`; the coordinator's `X-User-ID` is recorded as `created_by`, the lot starts in `DRAFT`, and its computed `minimum_bid_cents` starts at zero. Pricing is per item and then aggregated: each lotted item's `floor_price_cents` is its `declared_value_cents` multiplied by the rate for its `value_tier` — 10% for `LOW`, 20% for `MID`, 30% for `HIGH` — rounded half-up to whole cents, and the lot's `minimum_bid_cents` is the sum of those already-rounded floors. The rounding order is pinned (§2.10): round each item's floor first, then sum; an empty lot's minimum is zero. The minimum is recomputed on every addition, every removal, and every cascade that empties a lot. An item may appear in at most one non-terminal lot at a time, and lot lists accept `event_id` and `status` filters.

Adding an item to a lot is concurrency-guarded per §2.6 through `expected_lot_version`, and its checks run in order: the stale-version rejection (`ERR_STALE_LOT_VERSION`), the lot must be `DRAFT` (`ERR_INVALID_STATE`), the item must be `AUCTION_ELIGIBLE` (`ERR_ITEM_NOT_AUCTION_ELIGIBLE`), the item's `program_id` must equal the event's `program_id` (`ERR_CROSS_PROGRAM_REFERENCE`), and the lot's current `minimum_bid_cents` plus the candidate item's floor price must not exceed the venue's `insurance_cap_cents` (`ERR_INSURANCE_CAP_EXCEEDED`). A successful addition creates the lot-item row with its computed `floor_price_cents`, transitions the item from `AUCTION_ELIGIBLE` to `LOTTED`, recomputes the lot minimum, increments both the lot's and the item's versions, and answers 201 Created. Removing an item from a `DRAFT` lot reverses it without penalty: the membership row is deleted, the item returns from `LOTTED` to `AUCTION_ELIGIBLE` with no change to `unsold_count`, the minimum is recomputed, both versions increment, and the removal answers 204 with no body. Membership rows can be listed per lot or across lots with `lot_id` and `item_id` filters.

Publishing moves a `DRAFT` lot to `PUBLISHED` and requires at least one membership row — publishing an empty lot is rejected with `ERR_LOT_EMPTY`. Once published, a lot meets one of two fates. Finalizing the sale records the winning `hammer_price_cents`, a non-negative integer count of cents: the lot must be `PUBLISHED`, then the finalizing coordinator's `X-User-ID` must differ from the lot's `created_by` (`ERR_SEGREGATION_OF_DUTIES`), then the hammer price must be at least the lot's `minimum_bid_cents` (`ERR_BELOW_MINIMUM_BID`, HTTP 422), in that order. Success stamps `hammer_price_cents`, records `finalized_by`, moves the lot to `SOLD`, transitions every lotted item from `LOTTED` to `SOLD`, frees their storage slots, and increments the lot's and each item's version.

Closing a lot unsold moves `PUBLISHED` to `CLOSED_UNSOLD` and runs the per-item unsold escalation: each lotted item's `unsold_count` increments by one, and an item whose count has reached 2 moves to `DISPOSAL_PENDING` with `pending_disposal_method` fixed to `DESTRUCTION`, while an item still below 2 returns to `AUCTION_ELIGIBLE`. The lot's membership rows are deleted, its `minimum_bid_cents` is recomputed to zero, and every affected item's version increments along with the lot's. Manual removal and event cancellation never increment `unsold_count` — only an unsold close does.

Cancelling a `SCHEDULED` event cascades: every one of its lots in `DRAFT` or `PUBLISHED` becomes `CANCELLED`, every item lotted in those lots returns from `LOTTED` to `AUCTION_ELIGIBLE` with no change to `unsold_count`, their membership rows are deleted, each affected lot's `minimum_bid_cents` is recomputed to zero, and the event's, each lot's, and each item's versions increment.

Settlement closes the books on a finished event. Its three preconditions are checked in order: the event must be `SCHEDULED` (`ERR_INVALID_STATE`), every lot of the event must be in `SOLD`, `CLOSED_UNSOLD`, or `CANCELLED` (`ERR_LOTS_NOT_FINAL`), and the logical clock must have reached the event's `ends_at` (`ERR_EVENT_STILL_OPEN`). Settlement then computes the money in a pinned order: `gross_proceeds_cents` is the sum of `hammer_price_cents` over the event's `SOLD` lots only, excluding `CLOSED_UNSOLD` and `CANCELLED` lots; the commission rate is keyed on that gross — 10% when gross is below 1,000,000 cents, 8% when gross is at least 1,000,000 but below 5,000,000 cents, and 6% when gross is 5,000,000 cents or more; `total_commission_cents` is the sum over each `SOLD` lot of that lot's hammer price multiplied by the rate and rounded half-up to whole cents, rounding per lot before summing; and `net_proceeds_cents` is the gross minus the total commission. An event with no `SOLD` lots settles to zero on all three figures. The event becomes `COMPLETED`, terminal alongside `CANCELLED`, and its version increments.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created` — this includes action-style creates such as referring an item to law enforcement (which creates the referral case) and adding an item to a lot (which creates the membership row). Operations that modify an existing resource return `200 OK`. Removing an item from a lot returns `204 No Content` with no response body. In the table below, "All staff" denotes the seven-role staff set: `IntakeOfficer`, `PropertyCustodian`, `ClaimsExaminer`, `ReleaseOfficer`, `PoliceLiaison`, `AuctionCoordinator`, and `ProgramAdmin`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server's logical clock | ProgramAdmin |
| POST | `/_sweeps/retention` | Run the retention-expiry sweep | ProgramAdmin |
| POST | `/programs` | Create a lost-and-found program (TRANSIT or FACILITY) | ProgramAdmin |
| GET | `/programs` | List programs | All staff |
| GET | `/programs/{program_id}` | Get one program | All staff |
| POST | `/programs/{program_id}/deactivate` | Deactivate a program | ProgramAdmin |
| POST | `/retention-policies` | Create a retention policy (supersedes same key; OCC on program) | ProgramAdmin |
| GET | `/retention-policies` | List retention policies | All staff |
| GET | `/retention-policies/{policy_id}` | Get one retention policy | All staff |
| POST | `/storage-locations` | Create a storage location | ProgramAdmin |
| GET | `/storage-locations` | List storage locations | All staff |
| GET | `/storage-locations/{location_id}` | Get one storage location including computed occupancy | All staff |
| POST | `/storage-locations/{location_id}/deactivate` | Deactivate an empty storage location | ProgramAdmin |
| POST | `/venues` | Create an auction venue | ProgramAdmin |
| GET | `/venues` | List venues | All staff |
| GET | `/venues/{venue_id}` | Get one venue | All staff |
| POST | `/claimants` | Register a claimant (public self-service) | PublicUser |
| GET | `/claimants/{claimant_id}` | Get a claimant; Claimant role reads only its own | ClaimsExaminer, ReleaseOfficer, ProgramAdmin, Claimant |
| POST | `/claimants/{claimant_id}/verify-id` | Mark the claimant's ID as verified | ClaimsExaminer |
| POST | `/items` | Register found property | IntakeOfficer |
| GET | `/items` | Staff item list with filters | All staff |
| GET | `/items/{item_id}` | Staff item read | All staff |
| GET | `/public/items` | Public searchable inventory (LISTED, non-identification only) | PublicUser, Claimant |
| POST | `/items/{item_id}/publish` | Make a stored item publicly searchable | IntakeOfficer |
| POST | `/items/{item_id}/unpublish` | Remove an item from public search | IntakeOfficer |
| POST | `/items/{item_id}/move` | Move an item to a different storage location | PropertyCustodian |
| POST | `/items/{item_id}/dispose` | Dispose of a DISPOSAL_PENDING item | PropertyCustodian |
| POST | `/items/{item_id}/release` | Release an item with an approved claim to its owner | ReleaseOfficer |
| POST | `/items/{item_id}/refer-to-law-enforcement` | Refer a stored/listed item to law enforcement | PoliceLiaison |
| GET | `/referrals` | List referral cases | All staff |
| GET | `/referrals/{referral_id}` | Get one referral case | All staff |
| POST | `/referrals/{referral_id}/confirm-pickup` | Confirm law enforcement picked up the item | PoliceLiaison |
| POST | `/referrals/{referral_id}/return-to-custody` | Record the item's return from law enforcement | PoliceLiaison |
| POST | `/referrals/{referral_id}/convert-to-evidence` | Convert the held item to evidence (terminal) | PoliceLiaison |
| POST | `/claims` | File an ownership claim (OCC on the item) | Claimant |
| GET | `/claims` | List claims; Claimant role sees only its own | ClaimsExaminer, ReleaseOfficer, PoliceLiaison, ProgramAdmin, Claimant |
| GET | `/claims/{claim_id}` | Get one claim; Claimant role reads only its own | ClaimsExaminer, ReleaseOfficer, PoliceLiaison, ProgramAdmin, Claimant |
| POST | `/claims/{claim_id}/start-review` | Begin examiner review | ClaimsExaminer |
| POST | `/claims/{claim_id}/request-info` | Ask the claimant for more evidence | ClaimsExaminer |
| POST | `/claims/{claim_id}/resubmit` | Claimant resubmits with new proof flags | Claimant |
| POST | `/claims/{claim_id}/approve` | Approve a claim (cascades to item and competing claims) | ClaimsExaminer |
| POST | `/claims/{claim_id}/reject` | Reject a claim under review | ClaimsExaminer |
| POST | `/claims/{claim_id}/withdraw` | Claimant withdraws an open claim | Claimant |
| POST | `/inquiries` | Submit a public inquiry | PublicUser |
| GET | `/inquiries` | List inquiries | All staff |
| GET | `/inquiries/{inquiry_id}` | Get one inquiry | All staff |
| POST | `/inquiries/{inquiry_id}/answer` | Answer an open inquiry | IntakeOfficer |
| POST | `/inquiries/{inquiry_id}/close` | Close an inquiry | IntakeOfficer |
| POST | `/auction-events` | Schedule an auction event at a venue | AuctionCoordinator |
| GET | `/auction-events` | List auction events | All staff |
| GET | `/auction-events/{event_id}` | Get one auction event | All staff |
| POST | `/auction-events/{event_id}/cancel` | Cancel a scheduled event (cascades to lots and items) | AuctionCoordinator |
| POST | `/auction-events/{event_id}/settle` | Settle a finished event (gross, commission, net) | AuctionCoordinator |
| POST | `/auction-lots` | Create a draft lot under an event | AuctionCoordinator |
| GET | `/auction-lots` | List lots | All staff |
| GET | `/auction-lots/{lot_id}` | Get one lot including computed minimum bid | All staff |
| POST | `/auction-lots/{lot_id}/items` | Add an AUCTION_ELIGIBLE item to a DRAFT lot (OCC on the lot) | AuctionCoordinator |
| DELETE | `/auction-lots/{lot_id}/items/{item_id}` | Remove an item from a DRAFT lot | AuctionCoordinator |
| GET | `/auction-lots/{lot_id}/items` | List membership rows of a lot | All staff |
| GET | `/lot-items` | List membership rows across lots | All staff |
| GET | `/lot-items/{lot_item_id}` | Get one membership row | All staff |
| POST | `/auction-lots/{lot_id}/publish` | Publish a non-empty DRAFT lot | AuctionCoordinator |
| POST | `/auction-lots/{lot_id}/finalize-sale` | Record hammer price and sell the lot | AuctionCoordinator |
| POST | `/auction-lots/{lot_id}/close-unsold` | Close a published lot without a sale | AuctionCoordinator |
| GET | `/release-records` | List release documentation records (append-only) | All staff |
| GET | `/release-records/{record_id}` | Get one release record | All staff |

## 5. Error Code Catalogue

The table below enumerates every error identifier and its HTTP status. The conditions that trigger each error are specified in the narratives of §2 and §3, not here.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_STALE_ITEM_VERSION` | 412 |
| `ERR_STALE_LOT_VERSION` | 412 |
| `ERR_STALE_PROGRAM_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_ITEM_NOT_CLAIMABLE` | 409 |
| `ERR_ITEM_NOT_AUCTION_ELIGIBLE` | 409 |
| `ERR_LOTS_NOT_FINAL` | 409 |
| `ERR_PROGRAM_INACTIVE` | 409 |
| `ERR_LOCATION_INACTIVE` | 409 |
| `ERR_LOCATION_NOT_EMPTY` | 409 |
| `ERR_STORAGE_CAPACITY_EXCEEDED` | 409 |
| `ERR_SECURE_STORAGE_REQUIRED` | 422 |
| `ERR_NO_RETENTION_POLICY` | 422 |
| `ERR_DISPOSAL_METHOD_MISMATCH` | 422 |
| `ERR_LOT_EMPTY` | 422 |
| `ERR_INVALID_TIME_WINDOW` | 422 |
| `ERR_VENUE_DOUBLE_BOOKED` | 409 |
| `ERR_EVENT_STILL_OPEN` | 409 |
| `ERR_CROSS_PROGRAM_REFERENCE` | 422 |
| `ERR_INSURANCE_CAP_EXCEEDED` | 422 |
| `ERR_BELOW_MINIMUM_BID` | 422 |
| `ERR_IDENTIFICATION_NOT_LISTABLE` | 422 |
| `ERR_CLAIM_PROOF_INSUFFICIENT` | 422 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
