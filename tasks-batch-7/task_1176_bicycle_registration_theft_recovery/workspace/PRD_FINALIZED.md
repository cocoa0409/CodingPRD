# Bicycle Theft Recovery API — Product Requirements Document

## 1. Introduction

Bicycle theft strands owners, police departments, and recovery shops in separate silos: a stolen frame surfaces at a pawn shop or a campus impound lot, yet there is no reliable way to connect it back to the person who reported it missing. This document specifies a community bicycle registry and theft-recovery platform in the style of public bike-index programs. Owners register bicycles with their frame serial number and a photo; they report sales and thefts; partner organizations — law enforcement agencies, bike shops, and campuses — intake recovered bicycles; and the platform scores candidate matches, notifies owners, adjudicates ownership claims, and disposes of unclaimed bicycles through a structured auction pipeline with a fully balanced financial ledger.

Three concerns dominate the design. First, registry accuracy: serial numbers arrive dirty from the field, so canonicalization, duplicate detection, and merge workflows are first-class features rather than housekeeping. Second, evidentiary discipline: theft reports pass through a registrar review loop, match candidates carry two independently computed scores, and claims require human approval before a bicycle changes hands. Third, fiscal accountability: every fee, storage charge, commission, and payout is posted to an append-only double-entry ledger whose credits and debits must always balance. All resources are mounted under the `/registry` prefix, and all time-dependent rules — transfer expiry, bidding windows, disposition waits, waiver validity — are evaluated against a server-side logical clock rather than wall-clock time.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API are authenticated through two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. The platform recognizes five roles: `Anonymous`, `Owner`, `Partner`, `Registrar`, and `Admin`. A request with missing or malformed headers, or whose `X-User-Role` is not one of these five declared values, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is well-formed but not permitted for the target endpoint is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403).

Identity semantics differ by role, and the distinction drives every ownership check in the system. When `X-User-Role` is `Owner`, `X-User-ID` is the `id` of the acting `Owner`; ownership checks on any resource that references an owner — bicycles, transfers, theft reports, claims, bids, event registrations, notifications — compare the resource's owner foreign-key field to `X-User-ID`, and a mismatch is rejected with `ERR_FORBIDDEN_RESOURCE_ACCESS` (HTTP 403). When `X-User-Role` is `Partner`, `X-User-ID` is the `id` of the acting `PartnerOrg`; a partner's access to recovery intakes is restricted to rows whose `partner_org_id` equals `X-User-ID`, with the same `ERR_FORBIDDEN_RESOURCE_ACCESS` rejection on mismatch. When `X-User-Role` is `Registrar` or `Admin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but never compares it to any entity's `id`. When `X-User-Role` is `Anonymous`, `X-User-ID` is likewise opaque and carries no ownership meaning — an `Anonymous` caller may do exactly one thing, self-register an owner account.

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

List endpoints paginate via two query parameters. The `limit` parameter caps the number of returned items; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips that many items from the front of the result set and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. The Logical Clock

The platform never consults wall-clock time for business rules. An admin-only test-driving capability sets the server's logical clock to a supplied `to_iso8601` instant and returns the resulting `current_utc`. Before any such call, the logical clock starts at exactly 2026-05-01T00:00:00Z, and once set it never falls back to wall-clock time. Every temporal rule in this document — the seven-day transfer acceptance window, auction open/close boundaries, the thirty-day disposition wait, event windows, waiver validity — evaluates against this logical clock, and server-stamped timestamps such as `flagged_at` and `closed_at` are taken from it.

### 2.5. Common Resource Properties

Every primary resource carries a standard set of system-managed fields:

- `id` (string): a server-minted UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, set at creation.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation.
- `version` (integer): a system-managed integer that increments by 1 with every modification to the resource, including modifications caused by a cascade from another entity's transition.

One entity breaks this convention deliberately: `LedgerEntry` is an append-only financial record and carries only `id` and `created_at`. Both `updated_at` and `version` are absent from ledger entries — a ledger row, once written, is never mutated; corrections are posted as new compensating rows (§3.7).

### 2.6. Validation Pipeline and Error Precedence

Every request passes through a fixed validation pipeline, and the stages are evaluated in a strict order — a failure at an earlier stage surfaces its error and masks every later-stage check. The ordered stages are:

1. **Authentication** — the `X-User-Role` and `X-User-ID` headers are present and well-formed, and the role is one of the declared roles; failures yield `ERR_UNAUTHENTICATED`.
2. **Role authorization** — the acting role appears in the endpoint's authorized role list; failures yield `ERR_UNAUTHORIZED_ROLE`.
3. **Entity-backed identity match** — owner-scoped endpoints are restricted to the acting owner's own resources, and partner endpoints to the acting partner's own organization, as described in §2.1; failures yield `ERR_FORBIDDEN_RESOURCE_ACCESS`.
4. **Input shape** — required fields are present, types are correct, enum values are in range, `starts_at` precedes `ends_at`, `capacity` is at least 1, monetary inputs respect their floors (`declared_value_cents` and `sale_price_cents` at least 0, `amount_cents` at least 1), `merged_into_bicycle_id` names one of the two bicycles on the flag, and a claim's `match_id` belongs to the same recovery intake as the claim's `recovery_intake_id`; failures yield `ERR_INVALID_REQUEST` (HTTP 400).
5. **Path existence, left to right** — each identifier in the URL path must resolve to an existing row, checked sequentially from the leftmost segment; the first unresolvable segment produces its entity-specific 404: `ERR_OWNER_NOT_FOUND`, `ERR_PARTNER_ORG_NOT_FOUND`, `ERR_BICYCLE_NOT_FOUND`, `ERR_TRANSFER_NOT_FOUND`, `ERR_THEFT_REPORT_NOT_FOUND`, `ERR_RECOVERY_INTAKE_NOT_FOUND`, `ERR_MATCH_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_AUCTION_NOT_FOUND`, `ERR_BID_NOT_FOUND`, `ERR_EVENT_NOT_FOUND`, `ERR_EVENT_REGISTRATION_NOT_FOUND`, `ERR_DUPLICATE_FLAG_NOT_FOUND`, or `ERR_NOTIFICATION_NOT_FOUND`.
6. **Body reference resolution** — foreign keys supplied in the request body (`bicycle_id`, `recovery_intake_id`, `match_id`, `host_org_id`, `bicycle_a_id`, `bicycle_b_id`, and the `to_owner_email` that must resolve to an existing owner) must each resolve to an existing row; failures yield the field-appropriate not-found error (`ERR_BICYCLE_NOT_FOUND`, `ERR_RECOVERY_INTAKE_NOT_FOUND`, `ERR_MATCH_NOT_FOUND`, `ERR_PARTNER_ORG_NOT_FOUND`, or `ERR_OWNER_NOT_FOUND`).
7. **Partner posture** — partner write operations require the acting partner's organization to be `ACTIVE`; failures yield `ERR_PARTNER_ORG_NOT_ACTIVE`.
8. **Optimistic concurrency** — guarded writes compare the client-supplied expected version to the current `version`; mismatches yield `ERR_STALE_VERSION` (§2.9).
9. **Bicycle transferability and merge guard** — operations on a bicycle verify it is in a permissible registry and integrity state; failures yield `ERR_BICYCLE_NOT_TRANSFERABLE` or `ERR_BICYCLE_MERGED`.
10. **State-machine from-state** — the target entity sits in a state from which the invoked action is defined; failures yield the action-specific conflict error (`ERR_TRANSFER_NOT_PENDING`, `ERR_THEFT_REPORT_NOT_ACTIONABLE`, `ERR_RECOVERY_NOT_ACTIONABLE`, `ERR_MATCH_NOT_OPEN`, `ERR_CLAIM_NOT_REVIEWABLE`, `ERR_AUCTION_NOT_OPEN`, `ERR_AUCTION_NOT_CLOSABLE`, `ERR_AUCTION_NOT_SETTLABLE`, `ERR_BID_NOT_RETRACTABLE`, `ERR_EVENT_NOT_PUBLISHED`, or `ERR_FLAG_NOT_OPEN`).
11. **Duplicate-suspect safety hold** — operations blocked while a bicycle is `DUPLICATE_SUSPECT` fail with `ERR_DUPLICATE_HOLD`.
12. **Uniqueness and graph constraints** — serial collisions, single-pending-transfer, self-transfer, single-open-report, event host and window rules, single-auction and auction-window rules, single-claim and single-booking rules; failures yield `ERR_DUPLICATE_SERIAL_ACTIVE`, `ERR_TRANSFER_ALREADY_PENDING`, `ERR_SELF_TRANSFER`, `ERR_REPORT_ALREADY_OPEN`, `ERR_EVENT_HOST_NOT_CAMPUS`, `ERR_EVENT_WINDOW_OVERLAP`, `ERR_AUCTION_ALREADY_EXISTS`, `ERR_AUCTION_WINDOW_CONFLICT`, `ERR_AUCTION_HAS_BIDS`, `ERR_INTAKE_HAS_ACTIVE_MATCH`, `ERR_CLAIM_ALREADY_EXISTS`, or `ERR_EVENT_REGISTRATION_EXISTS` as applicable.
13. **Waiver validity** — waiver codes are checked for resolvability, freshness, and event standing; failures yield `ERR_WAIVER_CODE_INVALID`.
14. **Temporal windows** — time-window rules for transfers, auctions, bids, dispositions, and event bookings; failures yield `ERR_TRANSFER_EXPIRED`, `ERR_AUCTION_NOT_YET_OPEN`, `ERR_AUCTION_WINDOW_EXPIRED`, `ERR_DISPOSITION_TOO_EARLY`, or `ERR_EVENT_ENDED`.
15. **Fiscal and quota checks** — bid minimums and event seat capacity, evaluated last; failures yield `ERR_BID_BELOW_MINIMUM` or `ERR_EVENT_CAPACITY_FULL`.

Because earlier stages mask later ones, the declared order is observable: for example, an unauthenticated caller always sees `ERR_UNAUTHENTICATED` even if the request body is also malformed, and a stale-version rejection always precedes any state-machine complaint.

### 2.7. Serial Number Canonicalization

Serial numbers are the registry's primary matching key, and they arrive filthy — mixed case, spaces, dashes, and characters that are trivially confused when stamped or transcribed. Canonicalization is therefore deterministic and applied identically everywhere. To produce a canonical serial from a raw serial string: uppercase the string, drop every character that is not a letter or digit, then apply a fixed confusable-character substitution to each remaining character — the letter O becomes the digit 0, I becomes 1, L becomes 1, S becomes 5, B becomes 8, Z becomes 2, G becomes 6, and Q becomes 0. The result is an exact string with no rounding or approximation. For example, the raw serial "ab c-123o" canonicalizes to "A8C1230".

A `Bicycle` stores this canonical form in `serial_normalized`, computed from the supplied `serial_number` at registration. A `RecoveryIntake` likewise stores `serial_normalized`, computed from the observed `serial_number_raw` at intake — that raw value may be partial or damaged, which is exactly why matching later scores serial similarity rather than demanding equality. Every duplicate-detection and match-scoring comparison in the system runs over canonical serials, never over raw input.

### 2.8. Monetary Precision and the Double-Entry Ledger

All monetary values are integer cents — never floats, never fractional cents. Where a calculation produces a fractional cent, the result is rounded half-up to the nearest integer cent. Several calculations pin a rounding order (per-component rounding before summation); those orders are contractual and are called out where the calculation is defined (§3.2, §3.7).

Every financial event posts to an append-only ledger of `LedgerEntry` rows. Each entry records an `entry_type` — one of `REGISTRATION_FEE`, `FEE_WAIVER`, `TRANSFER_FEE`, `STORAGE_FEE`, `AUCTION_COMMISSION`, `AUCTION_PARTNER_PAYOUT`, `AUCTION_ESCROW`, or `REVERSAL` — a `direction` of `DEBIT` or `CREDIT`, an `account` of `OWNER`, `PARTNER_ORG`, `PROGRAM`, or `ESCROW`, and a non-negative `amount_cents`. Contextual foreign keys are populated according to the entry's nature: `owner_id` when the account is `OWNER`, `partner_org_id` when the account is `PARTNER_ORG`, `auction_id` for auction-related entries, and `bicycle_id` for registration and transfer fee entries; a human-readable `reference_note` may record provenance. The governing invariant, evaluated over the whole table after every financial transition (registration, transfer acceptance, auction settlement, settlement void), is exact: the sum of `amount_cents` over all `CREDIT` rows minus the sum over all `DEBIT` rows equals zero. Every business event posts a balanced debit/credit set, and the void-settlement flow posts mirrored `REVERSAL` entries with directions swapped, so the invariant holds both before and after any compensating action.

### 2.9. Optimistic Concurrency Control

Exactly two write operations in the API are guarded by optimistic concurrency control, and each names its guard field explicitly.

An owner's update to a bicycle's descriptive fields must carry `expected_bicycle_version`, set to the `version` of the `Bicycle` the client last observed. If the bicycle's current `version` has advanced past that value — because another write landed in between — the update is rejected with `ERR_STALE_VERSION` (HTTP 412), forcing the client to re-read before overwriting.

Placing a bid must likewise carry `expected_auction_version`, set to the `version` of the target `Auction` the client last observed. Because every accepted bid itself advances the auction's `version` (§3.7), a bidder working from an outdated auction view is rejected with `ERR_STALE_VERSION` (HTTP 412) and must re-read the auction before bidding again.

No other endpoint accepts an expected-version field; all remaining writes proceed without an OCC check.

### 2.10. Parallel Status Dimensions and Cascade Consistency

A `Bicycle` carries two independent status dimensions that evolve in parallel. The `registry_status` dimension tracks the theft lifecycle — `REGISTERED`, `STOLEN`, `RECOVERED`, `RETURNED` — and is cyclic: a bicycle can move from `REGISTERED` to `STOLEN` and back to `REGISTERED` when a report is withdrawn. The `integrity_status` dimension tracks database accuracy — `CLEAR`, `DUPLICATE_SUSPECT`, `MERGED` — and is independent of the theft lifecycle; `MERGED` is terminal. Because the dimensions are parallel, no value of one implies anything about the other: a `STOLEN` bicycle can simultaneously be `DUPLICATE_SUSPECT`.

A bicycle whose `integrity_status` is `MERGED` is a retired record. Any business operation targeting a `MERGED` bicycle is rejected with `ERR_BICYCLE_MERGED` (HTTP 409); merged bicycles are also excluded from duplicate scans and from an owner's live bicycle count (§3.1, §3.8).

State changes propagate eagerly and atomically. When a transition on one entity forces transitions on other entities — flagging a report pushes its bicycle to `STOLEN` and cancels pending transfers; approving a claim advances the match, the intake, the bicycle, and the report in one chain — all of those mutations commit together within the same request. Every row touched by a cascade has its own `version` incremented by 1 and its own `updated_at` refreshed, so a client watching any single row always sees its evolution.

## 3. Business Logic & Workflows

### 3.1. Onboarding Owners and Partner Organizations

An `Anonymous` visitor joins the platform by self-registering an owner account with an `email`, a `password`, and a `full_name`; a `phone` contact may be supplied and defaults to null when omitted. Email uniqueness is enforced case-insensitively across all owners. The password is stored only as a hash and is never returned by any response. Once registered, an `Owner` may read their own record — and only their own; a `Registrar` or `Admin` may read any owner — and may update their `full_name` and `phone`, with each profile update incrementing the owner's `version` by 1. An owner's record also exposes `bikes_registered_count`, a computed count of the bicycles whose `current_owner_id` is this owner and whose `integrity_status` is not `MERGED`.

Partner organizations join through a different door: an `Admin` onboards each `PartnerOrg` directly, supplying its `name`, an `org_type` of `LAW_ENFORCEMENT`, `BIKE_SHOP`, or `CAMPUS`, a `jurisdiction_code` such as "SFPD-CENTRAL", and a `contact_email`. A new organization begins in `PENDING` status. From there an admin drives its lifecycle: activation moves `PENDING` to `ACTIVE`, and equally moves a `SUSPENDED` organization back to `ACTIVE`; suspension moves `ACTIVE` to `SUSPENDED`; revocation moves either `ACTIVE` or `SUSPENDED` to `REVOKED`, which is terminal. Each transition increments the organization's `version` by 1. Two computed counters track a partner's contribution: `total_recoveries_count`, the number of recovery intakes whose `partner_org_id` is this organization, and `storage_fees_earned_cents`, the sum of `amount_cents` over ledger entries of type `STORAGE_FEE` with direction `CREDIT` attributed to this organization. Registrars and admins may list partner organizations with optional `org_type` and `status` filters; a `Partner` may read only its own organization.

Partner write operations are gated on organizational standing. Intaking a recovered bicycle, running a match scan, completing a return handoff, and manually flagging a duplicate pair all require the acting partner's organization to be `ACTIVE`; an attempt from a `PENDING`, `SUSPENDED`, or `REVOKED` organization is rejected with `ERR_PARTNER_ORG_NOT_ACTIVE` (HTTP 409).

### 3.2. Registering a Bicycle: Fees, Waivers, and Duplicate Screening

An `Owner` registers a bicycle by supplying the `serial_number` as stamped on the frame, the `manufacturer`, the `model`, the `primary_color`, a `declared_value_cents` (which may not be negative), and a `photo_url` for the registration photo. An optional `photo_hash` — a 64-bit perceptual hash rendered as 16 lowercase hexadecimal characters, null when omitted — strengthens later forensic matching. Two opt-in extras, `engraving_opt_in` and `insurance_opt_in`, and an optional `waiver_code` complete the payload.

Registration computes and stores several derived values. The `serial_normalized` canonical key is produced per §2.7. The `current_owner_id` is set to the registering owner. The bicycle begins life with `registry_status` `REGISTERED` and `integrity_status` `CLEAR`. The `registration_fee_cents` is computed from the declared value and the chosen extras, and `waiver_code_used` records the waiver code consumed — null when none was applied.

The registration fee is assembled from four components, each rounded half-up to integer cents before any summation, and the pinned order matters: rounding happens per component first, and the rounded components are then summed — computing the sum of unrounded components and rounding once at the end is a different, forbidden order. The components are: a tier base of 1000 cents when the declared value is below 50000 cents, 2000 cents when it is at least 50000 and at most 200000 cents, or 3500 cents when it exceeds 200000 cents; an insurance component equal to eight percent of the declared value, rounded half-up, when `insurance_opt_in` is set, and zero otherwise; an engraving component of a flat 1500 cents when `engraving_opt_in` is set, and zero otherwise; and a processing component of three percent of the sum of the tier base, insurance, and engraving components, rounded half-up. The fee is the sum of these four rounded components.

When a valid `waiver_code` is supplied, the fee becomes zero after the per-component computation — the waiver applies a full discount — and the code is consumed. A waiver code is valid only when it resolves to an issued code that has not been used before, whose issuing event is not `CANCELLED`, and where the current logical time is no later than thirty days after that event's `ends_at`; any other code is rejected with `ERR_WAIVER_CODE_INVALID` (HTTP 422). Consumption flips the issuing event registration's `waiver_used` flag to true.

Either way, the fee posts a balanced ledger pair: a `DEBIT` to the `OWNER` account and a `CREDIT` to the `PROGRAM` account, both of type `REGISTRATION_FEE` for the computed amount, or both of type `FEE_WAIVER` for a zero amount when a waiver was applied, and both carrying the new bicycle's `bicycle_id`.

Registration also triggers the duplicate auto-scan. The new bicycle is compared against every pre-existing bicycle whose `integrity_status` is not `MERGED`, processed in `created_at` ascending order. Two outcomes are possible per compared pair. An exact `serial_normalized` equality with an existing `CLEAR` bicycle is rejected outright with `ERR_DUPLICATE_SERIAL_ACTIVE` (HTTP 409) — the platform will not register a second live record for the same canonical serial. A non-exact pair whose duplicate confidence reaches at least 8500 basis points auto-creates a `DuplicateFlag` in `OPEN` status and flips both bicycles' `integrity_status` from `CLEAR` to `DUPLICATE_SUSPECT` (incrementing each bicycle's `version`); the auto-created flag records `bicycle_a_id` as the pre-existing bicycle and `bicycle_b_id` as the newly created one.

The duplicate confidence score itself is a weighted blend over the canonical serials and descriptive fields. Serial points are full credit when the two normalized serials are identical, and otherwise one minus the Levenshtein edit distance between them divided by the length of the longer normalized serial, never below zero. Manufacturer points are full credit when the two manufacturer strings match case-insensitively, and zero otherwise; model points follow the same rule over the model strings. The confidence is the weighted sum — serial points at weight 0.60, manufacturer points at 0.25, model points at 0.15 — multiplied by 10000 and rounded half-up to an integer number of basis points between 0 and 10000.

Owners always see only their own bicycles in list views — the `current_owner_id` filter is forced to the caller — and may narrow results with `serial_number`, `registry_status`, and `integrity_status` filters. A `Partner` may search across all bicycles as part of stolen-registry checks, but reading a single bicycle record is restricted: a partner sees the full record only while the bicycle's `registry_status` is `STOLEN`.

After registration, an owner may update a bicycle's descriptive fields — `model`, `primary_color`, `photo_url`, `photo_hash` — through the OCC-guarded update described in §2.9; the bicycle's identifying serial and declared value are not editable. A successful update increments `version` by 1.

### 3.3. Ownership Transfers and Sale Reporting

When a bicycle changes hands, the seller reports the sale by initiating an ownership transfer with the `bicycle_id`, the buyer's `to_owner_email`, and the `sale_price_cents` (which may not be negative). The buyer email must resolve to an existing owner (`ERR_OWNER_NOT_FOUND` otherwise), and the resolved buyer is stored as `to_owner_id` while the acting seller is recorded as `from_owner_id`. The transfer begins in `PENDING_ACCEPTANCE` status with an `expires_at` of exactly seven days after creation.

Several guards protect the transfer at creation. The bicycle's `registry_status` must be `REGISTERED` — a `STOLEN`, `RECOVERED`, or `RETURNED` bicycle cannot be sold through the registry, and the attempt is rejected with `ERR_BICYCLE_NOT_TRANSFERABLE`. A `MERGED` bicycle rejects the operation with `ERR_BICYCLE_MERGED`, and a `DUPLICATE_SUSPECT` bicycle is under a safety hold and rejects with `ERR_DUPLICATE_HOLD`. At most one `PENDING_ACCEPTANCE` transfer may exist per bicycle; a second attempt fails with `ERR_TRANSFER_ALREADY_PENDING`. Seller and buyer must be different owners — a `to_owner_email` resolving to the seller fails with `ERR_SELF_TRANSFER` (HTTP 422).

Acceptance belongs to the buyer. The acting owner must be the transfer's `to_owner_id`, the transfer must still be `PENDING_ACCEPTANCE` (otherwise `ERR_TRANSFER_NOT_PENDING`), and the current logical time must be no later than `expires_at`. An acceptance attempted past expiry does not simply fail: the transfer first auto-transitions to `EXPIRED` — a lazy expiry that increments its `version` — and the call then fails with `ERR_TRANSFER_EXPIRED`. Acceptance also re-verifies at accept time that the bicycle is `REGISTERED` and `CLEAR`, since a duplicate flag may have appeared while the offer was open. A successful acceptance moves the bicycle's `current_owner_id` to the buyer and increments the bicycle's `version`, posts a transfer-fee ledger pair — a `DEBIT` of 300 cents to the buyer's `OWNER` account and a `CREDIT` of 300 cents to the `PROGRAM` account, both of type `TRANSFER_FEE` and both carrying the `bicycle_id` — creates a `TRANSFER_COMPLETED` notification for the `from_owner_id` seller, and moves the transfer to `COMPLETED` with its own `version` incremented.

Rejection likewise belongs to the buyer and requires `PENDING_ACCEPTANCE`; it moves the transfer to `REJECTED`. Cancellation belongs to the seller — the acting owner must be the `from_owner_id` — and moves a `PENDING_ACCEPTANCE` transfer to `CANCELLED`; like acceptance, a cancel attempted after `expires_at` triggers the lazy auto-transition to `EXPIRED` and fails with `ERR_TRANSFER_EXPIRED`. Transfers can also be cancelled without any participant action: the theft-flag cascade (§3.4) and the merge cascade (§3.8) both force pending transfers to `CANCELLED`.

List views support `bicycle_id`, `from_owner_id`, `to_owner_id`, and `status` filters; an owner sees only transfers in which they are the sending or receiving party.

### 3.4. Theft Reports and the Registrar Review Loop

When a bicycle is stolen, its owner files a theft report with the `bicycle_id`, the `occurred_at` time of the theft, a free-text `theft_location`, and optionally a `police_case_number` and a `description` of the circumstances. The reporting owner is recorded as `owner_id`, and the report begins in `UNDER_REVIEW` status. A bicycle may have at most one non-terminal theft report — one in `UNDER_REVIEW`, `NEEDS_INFO`, or `FLAGGED`; a second filing while one is open is rejected with `ERR_REPORT_ALREADY_OPEN`.

Review is a dialogue, and the loop between registrar and owner is unbounded. A `Registrar` who needs more detail sends the report from `UNDER_REVIEW` to `NEEDS_INFO`, supplying an `info_request_text` that is stored on the report. The owner — and only the report's owner — answers by moving the report from `NEEDS_INFO` back to `UNDER_REVIEW`, supplying a `response_text` that is likewise stored. Either action invoked from a state that does not allow it is rejected with `ERR_THEFT_REPORT_NOT_ACTIONABLE`. A registrar may instead close the dialogue by rejecting the report, from either `UNDER_REVIEW` or `NEEDS_INFO`, recording a `reason_text`; rejection is terminal.

The pivotal registrar action is flagging. Flagging requires the report to be `UNDER_REVIEW` and the bicycle's `integrity_status` to be anything other than `MERGED`. On flag, the report moves to `FLAGGED`, its `flagged_at` is stamped from the current logical clock, and its `version` increments — and then the cascade fires. The bicycle's `registry_status` moves from `REGISTERED` to `STOLEN`, incrementing the bicycle's `version`. Every `PENDING_ACCEPTANCE` transfer on that bicycle is force-cancelled to `CANCELLED`, each such transfer's `version` increments, and each cancellation creates a `TRANSFER_CANCELLED_STOLEN` notification addressed to that transfer's `to_owner_id` buyer. Finally, a `REPORT_FLAGGED` notification is created for the bicycle's `current_owner_id`. One registrar action, one atomic bundle of registry truth.

Owners retain the right to stand down their own reports. Withdrawal moves a report to `WITHDRAWN` from `UNDER_REVIEW` or from `NEEDS_INFO` with no further ceremony. Withdrawing a `FLAGGED` report — the owner found the bike — is heavier: it is permitted only while no `MatchCandidate` on this report stands in `CONFIRMED` status (an attempt otherwise fails with `ERR_THEFT_REPORT_NOT_ACTIONABLE`), and it unwinds the flag. The bicycle's `registry_status` returns from `STOLEN` to `REGISTERED`, and every match candidate on this report still in `PROPOSED` or `NOTIFIED` transitions to `EXPIRED`, each with its own `version` increment. A report whose match has been confirmed moves to `CLOSED_RECOVERED` instead, via the claim-approval cascade described in §3.6; `REJECTED`, `WITHDRAWN`, and `CLOSED_RECOVERED` are the terminal states.

Visibility follows involvement: an owner sees only their own reports, a `Partner` sees only `FLAGGED` reports (the actionable stolen-registry feed), and registrars and admins see all. List views accept `bicycle_id`, `owner_id`, and `status` filters.

### 3.5. Recovery Intake and Match Scoring

When a partner organization takes custody of a recovered bicycle, a `Partner` operator records the intake with the `serial_number_raw` exactly as observed on the frame — partial or damaged readings are expected — plus the observed `primary_color`, the `found_at` time, the `found_location`, and an `appraised_value_cents` (which may not be negative) that will later drive the storage cap and auction reserve. Observed `manufacturer`, `model`, `photo_url`, and `photo_hash` are optional and default to null. The intake is attributed to the acting partner's organization via `partner_org_id`, its `serial_normalized` is computed per §2.7, and it begins in `INTAKE` status. A partner's intakes are visible to that partner's own organization; registrars and admins see all, and list views accept `partner_org_id` and `status` filters.

Matching is an explicit, re-runnable act. A `Partner` or `Registrar` triggers a scan of an intake, and the scan computes a match score against every theft report currently in `FLAGGED` status — reports in any other status are excluded from the candidate set entirely. Candidates are processed in the reports' `created_at` ascending order. For each (intake, report) pair the scan creates one `MatchCandidate`, or recomputes and stores fresh scores if that pair already has one, and the response reports the `created_match_ids` alongside the `scanned_report_count`. Each match candidate records the `recovery_intake_id`, the `theft_report_id`, and a `bicycle_id` denormalized from the report's bicycle for filtering; list views accept `recovery_intake_id`, `theft_report_id`, `bicycle_id`, and `status` filters. An owner reading matches sees those tied to their own theft reports.

Every candidate carries two independently computed scores, both integer basis points between 0 and 10000, rounded half-up. Both variants share the same five evidence inputs. The temporal distance is the number of whole 86400-second days between the report's `occurred_at` and the intake's `found_at`, rounded down, never below zero. Serial points compare the intake's normalized serial to the bicycle's normalized serial: full credit on equality, otherwise one minus the Levenshtein distance divided by the longer serial's length, never below zero. Manufacturer points grant half credit when the intake's `manufacturer` was not observed (null), and otherwise full credit on a case-insensitive match with the bicycle's manufacturer or zero on a mismatch; color points follow the identical pattern over `primary_color`. Photo points are zero whenever either side lacks a `photo_hash`, and otherwise one minus the Hamming distance between the two hashes divided by 64. Temporal points are full credit when the gap is no more than thirty days; beyond that the credit is one minus the excess days beyond thirty divided by three hundred thirty-five, never below zero, so it reaches exactly zero at a gap of three hundred sixty-five days.

The **screening** variant weights serial evidence heaviest: 0.50 on serial points, 0.20 on manufacturer, 0.15 on color, and 0.15 on temporal, ignoring photo evidence entirely. The **forensic** variant rebalances toward physical evidence: 0.35 on serial, 0.30 on photo, 0.15 on manufacturer, 0.10 on color, and 0.10 on temporal. Each variant multiplies its weighted sum by 10000 and rounds half-up; the results are stored as `screening_score` and `forensic_score`. Identical inputs can diverge — when the photo is missing and serial, manufacturer, and temporal evidence are all full while color mismatches, the screening score is 8500 while the forensic score is 6000. Only the screening score ever drives status and notification; the forensic score is advisory, computed and stored alongside for registrar review.

A candidate's initial status is chosen at scan time: `NOTIFIED` when the screening score reaches at least 7000 basis points, otherwise `PROPOSED`. Entering `NOTIFIED` — whether at first scan or later, when a re-scan recomputes a `PROPOSED` candidate's screening score at 7000 or above — creates a `MATCH_FOUND` notification for the theft report's owner. A `Registrar` may dismiss a candidate from either `PROPOSED` or `NOTIFIED`, moving it to `DISMISSED`; any other source state fails with `ERR_MATCH_NOT_OPEN`. Candidates leave the board passively too: withdrawal of the underlying flagged report, or confirmation of a sibling match on the same intake, moves every affected `PROPOSED` or `NOTIFIED` candidate to `EXPIRED` (§3.4, §3.6). `CONFIRMED`, `DISMISSED`, and `EXPIRED` are terminal.

### 3.6. Ownership Claims and the Return Pipeline

A notified match does not itself return a bicycle — the owner must prove ownership. An `Owner` files a claim with the `recovery_intake_id`, the `match_id`, and a `proof_text` narrative describing receipts, photos, or distinguishing marks. The referenced match must be in `NOTIFIED` status (otherwise `ERR_MATCH_NOT_OPEN`), its theft report must belong to the claiming owner (otherwise `ERR_FORBIDDEN_RESOURCE_ACCESS`), and the match must belong to the same intake the claim names (otherwise `ERR_INVALID_REQUEST`). At most one `UNDER_REVIEW` claim may exist per match; a duplicate filing fails with `ERR_CLAIM_ALREADY_EXISTS`. The claim records the acting owner as `owner_id` and begins `UNDER_REVIEW`.

Approval is the system's deepest cascade, and a `Registrar` performs it only when four conditions hold, each with its own rejection: the claim is `UNDER_REVIEW` (otherwise `ERR_CLAIM_NOT_REVIEWABLE`); the intake is still `INTAKE` — the first approved claim wins, and a second approval attempt against an intake that has moved on fails with `ERR_RECOVERY_NOT_ACTIONABLE`; the referenced match is still `NOTIFIED`; and the matched bicycle's `integrity_status` is not `DUPLICATE_SUSPECT`, a safety hold whose violation fails with `ERR_DUPLICATE_HOLD`. On approval the chain fires in order: the match moves from `NOTIFIED` to `CONFIRMED`; the intake moves from `INTAKE` to `CLAIM_PENDING`; the bicycle's `registry_status` moves from `STOLEN` to `RECOVERED`; the theft report moves from `FLAGGED` to `CLOSED_RECOVERED`; every other match candidate on the same intake still in `PROPOSED` or `NOTIFIED` moves to `EXPIRED`; a `CLAIM_APPROVED` notification is created for the claiming owner; and every row in the chain — claim, match, intake, bicycle, report, sibling matches — has its own `version` incremented.

Rejection is the lightweight sibling: a registrar rejects an `UNDER_REVIEW` claim, the supplied `reason_text` is stored on the claim, a `CLAIM_REJECTED` notification goes to the owner, and the claim becomes `REJECTED`. An owner may also withdraw their own `UNDER_REVIEW` claim, moving it to `WITHDRAWN`.

The final mile belongs to the partner holding the bicycle. Completing the return requires the intake to be `CLAIM_PENDING` (otherwise `ERR_RECOVERY_NOT_ACTIONABLE`) and the acting partner's organization to be the intake's `partner_org_id`. On completion the intake moves from `CLAIM_PENDING` to `RETURNED`, the bicycle's `registry_status` moves from `RECOVERED` to `RETURNED`, and both rows increment their `version`. `RETURNED` is terminal for the intake, closing the recovery story.

Claim list views accept `recovery_intake_id`, `owner_id`, `match_id`, and `status` filters; an owner sees only their own claims.

### 3.7. Disposition of Unclaimed Bicycles and the Auction Pipeline

Some recovered bicycles are never claimed. A `Registrar` may mark an intake unclaimed only after a waiting period and a clear board: the intake must be in `INTAKE` status, the current logical time must be at least thirty days after the intake's `created_at` (an earlier attempt fails with `ERR_DISPOSITION_TOO_EARLY`), no match candidate for the intake may remain in `PROPOSED` or `NOTIFIED` (otherwise `ERR_INTAKE_HAS_ACTIVE_MATCH`), and no claim on the intake may be `UNDER_REVIEW` (otherwise `ERR_CLAIM_ALREADY_EXISTS`). A successful marking moves the intake from `INTAKE` to `UNCLAIMED`.

Disposition then runs through a registrar-managed auction. Scheduling an auction takes the `recovery_intake_id`, a `starts_at`, and an `ends_at` (which must be later than `starts_at`). Exactly one non-`CANCELLED` auction may exist per intake — and this `ERR_AUCTION_ALREADY_EXISTS` check is deliberately evaluated before the intake's state check, so the constraint error surfaces even when a previous scheduling has already moved the intake on to `DISPOSITION_SCHEDULED`. The intake must be `UNCLAIMED` (otherwise `ERR_RECOVERY_NOT_ACTIONABLE`). A neighborhood rule protects the partner's calendar: the new auction's window — and only the new auction's window — is inflated by twelve hours on each side, and that inflated window must not overlap the scheduled (uninflated) window of any other non-`CANCELLED` auction belonging to the same partner organization, or scheduling fails with `ERR_AUCTION_WINDOW_CONFLICT`; consequently, a clear gap of twelve hours or more between the two scheduled windows is always sufficient to avoid conflict. Scheduling moves the intake from `UNCLAIMED` to `DISPOSITION_SCHEDULED` and starts the auction in `SCHEDULED` status.

Two computed structures are fixed at creation. The `reserve_price_cents` is the larger of 1000 cents and twenty percent of the intake's `appraised_value_cents` rounded half-up. Then the estimate variant of the settlement waterfall runs, writing `estimated_storage_fee_cents`, `estimated_program_commission_cents`, and `estimated_partner_payout_cents`. The waterfall's evaluation order is pinned and contractual — later steps depend on earlier ones, so evaluating in any other order is undefined: first, the gross is the `reserve_price_cents`; second, the storage cutoff is the scheduled `ends_at`; third, the storage fee is the smaller of the accrued storage through that cutoff and thirty percent of the gross rounded half-up; fourth, the base is the gross minus the storage fee; fifth, the commission is ten percent of the portion of the base up to 50000 cents, rounded half-up, plus fifteen percent of any portion of the base above 50000 cents, rounded half-up, with the two rounded tier components then summed; sixth, the partner payout is the gross minus the storage fee minus the commission.

Storage accrual itself follows the same rule in both estimate and final variants, differing only in the cutoff. The first five days after intake creation are free: chargeable days are the whole 86400-second days elapsed between the intake's `created_at` and the cutoff, minus five, never below zero — so at exactly five days elapsed the chargeable count is zero. Each chargeable day costs 150 cents, and the accrued total is capped at twenty-five percent of the intake's appraised value, rounded half-up. The storage fee is the smaller of the accrued amount and that cap.

Opening the bidding requires the auction to be `SCHEDULED`, the current logical time to have reached `starts_at` (otherwise `ERR_AUCTION_NOT_YET_OPEN`), and not to have passed `ends_at` (otherwise `ERR_AUCTION_WINDOW_EXPIRED`); the auction then moves to `OPEN`. Owners bid by placing an `amount_cents` of at least 1 together with the OCC guard `expected_auction_version` (§2.9). Bids are accepted only while the auction is `OPEN` (otherwise `ERR_AUCTION_NOT_OPEN`) and the current time is no later than `ends_at` (otherwise `ERR_AUCTION_WINDOW_EXPIRED`). The placement records `auction_id` from the path and the acting owner as `bidder_owner_id`, creates the bid in `ACTIVE` status, and increments the auction's `version` by 1.

The minimum acceptable bid is computed at placement time. When no `ACTIVE` bid exists on the auction, the minimum is the `reserve_price_cents`. Otherwise the leading amount is the highest `amount_cents` among `ACTIVE` bids, the increment is the larger of 500 cents and five percent of that leading amount rounded half-up, and the minimum is the leading amount plus the increment. Acceptance is inclusive: a bid exactly equal to the minimum is accepted, while one cent below it is rejected with `ERR_BID_BELOW_MINIMUM` (HTTP 422). Lower earlier bids are not displaced at placement time — multiple `ACTIVE` bids coexist until close, and because a later bid must strictly exceed the leader, ties at close are impossible.

A bidder may change their mind under narrow conditions: retracting requires the bid to be `ACTIVE`, the acting owner to be the bid's `bidder_owner_id`, the auction still `OPEN`, and the bid not to be the highest-amount `ACTIVE` bid on its auction — the leader is locked in, and any violation fails with `ERR_BID_NOT_RETRACTABLE`. A successful retraction moves the bid to `RETRACTED`.

Closing is a registrar action requiring the auction to be `OPEN` and the current logical time to be at or past `ends_at` (otherwise `ERR_AUCTION_NOT_CLOSABLE`). Closing stamps `closed_at` from the logical clock, increments the auction's `version`, and ranks the field: the highest-amount `ACTIVE` bid moves to `WINNING`, and every other `ACTIVE` bid moves to `OUTBID` with a `BID_OUTBID` notification created for each outbid `bidder_owner_id`.

Settlement, again registrar-run, requires `CLOSED` (otherwise `ERR_AUCTION_NOT_SETTLABLE`). When a `WINNING` bid exists, the final variant of the waterfall runs with the winning bid's amount as the gross and `closed_at` as the storage cutoff — the same pinned six-step order as the estimate — writing `final_storage_fee_cents`, `final_program_commission_cents`, and `final_partner_payout_cents`, and recording `winning_bid_id` as the winning bid's `id`. The `WINNING` bid moves to `WON`, every `OUTBID` bid moves to `LOST`, an `AUCTION_WON` notification goes to the winning bidder, and the intake moves from `DISPOSITION_SCHEDULED` to `DISPOSED`. A balanced ledger set posts: the winning amount as a `DEBIT` to the winner's `OWNER` account and a `CREDIT` to the `ESCROW` account, both of type `AUCTION_ESCROW`; the storage fee as a `DEBIT` from `ESCROW` and a `CREDIT` to the `PARTNER_ORG` account, both `STORAGE_FEE`; the commission as a `DEBIT` from `ESCROW` and a `CREDIT` to `PROGRAM`, both `AUCTION_COMMISSION`; and the partner payout as a `DEBIT` from `ESCROW` and a `CREDIT` to `PARTNER_ORG`, both `AUCTION_PARTNER_PAYOUT`. When no `WINNING` bid exists — no bids were ever placed — the auction still settles: it moves to `SETTLED` with all final fields and `winning_bid_id` left null, the intake is still `DISPOSED`, and no ledger entries are created. Estimate and final variants legitimately diverge: a close later than the scheduled `ends_at` accrues additional storage days, and the winning bid rather than the reserve drives the gross — with a reserve of 20000 cents and a scheduled end forty days after intake, the estimate projects a partner payout of 13275 cents, while a winning bid of 30000 cents closed on day forty-three settles to a final payout of 21870 cents.

A settled auction can be financially undone without rewriting history. Voiding the settlement — allowed only from `SETTLED` (otherwise `ERR_AUCTION_NOT_SETTLABLE`) — moves the auction to `VOIDED` and, for every ledger entry created by the settle, appends a mirrored `REVERSAL` entry with the direction swapped and an equal `amount_cents`, preserving double-entry balance exactly. The void is financial only: the intake remains `DISPOSED`.

Cancellation covers the pre-settlement exits. From `SCHEDULED` an auction may always be cancelled; from `OPEN` cancellation requires that zero bids exist (otherwise `ERR_AUCTION_HAS_BIDS`); either path moves the auction to `CANCELLED` and returns the intake from `DISPOSITION_SCHEDULED` to `UNCLAIMED`, restoring it to the disposition queue. Cancelling from a terminal state fails with `ERR_AUCTION_NOT_SETTLABLE`. `SETTLED`, `VOIDED`, and `CANCELLED` are terminal for the auction.

Auction list views accept `recovery_intake_id` and `status` filters; bid list views accept `auction_id`, `bidder_owner_id`, and `status` filters, and an owner sees only their own bids.

### 3.8. Duplicate Flags and Registry Accuracy

Beyond the automatic scan at registration (§3.2), suspect pairs can be raised by hand. A `Partner` (from an `ACTIVE` organization, per §3.1) or a `Registrar` flags a pair by naming `bicycle_a_id` and `bicycle_b_id` — which must be two different bicycles, or the request fails with `ERR_INVALID_REQUEST` — with an optional `note`. The flag's `confidence_score` is computed with the same weighted duplicate-confidence rule used by the auto-scan, the flag opens in `OPEN` status, and both named bicycles move from `CLEAR` to `DUPLICATE_SUSPECT`, each incrementing its `version`.

A `DUPLICATE_SUSPECT` bicycle is under a safety hold: creating a transfer for it fails with `ERR_DUPLICATE_HOLD`, and approving a claim whose confirmed match references it fails the same way, until the flag is resolved.

Resolution is a registrar decision with two symmetric exits. Confirming a flag requires it to be `OPEN` (otherwise `ERR_FLAG_NOT_OPEN`) and takes the survivor's identity as `merged_into_bicycle_id`, which must be one of the two bicycles on the flag (otherwise `ERR_INVALID_REQUEST`). The other bicycle — the loser — moves from `DUPLICATE_SUSPECT` to `MERGED`, and the merge cascade strips its open obligations: every theft report on the loser still in `UNDER_REVIEW` or `NEEDS_INFO` moves to `WITHDRAWN`, and every `PENDING_ACCEPTANCE` transfer on the loser moves to `CANCELLED`. The survivor returns from `DUPLICATE_SUSPECT` to `CLEAR`. The flag stores the chosen `merged_into_bicycle_id` and moves to `CONFIRMED`; flag, loser, and survivor each increment their `version`. Dismissing a flag, likewise from `OPEN`, exonerates the pair: both bicycles return from `DUPLICATE_SUSPECT` to `CLEAR`, each incrementing its `version`, and the flag moves to `DISMISSED`. `CONFIRMED` and `DISMISSED` are terminal.

`MERGED` is forever. A merged bicycle remains readable as a historical record but accepts no further business operations (`ERR_BICYCLE_MERGED`, §2.10), drops out of the duplicate scan population, and no longer counts toward its owner's `bikes_registered_count`.

Flag list views accept `bicycle_a_id`, `bicycle_b_id`, `merged_into_bicycle_id`, and `status` filters, and are available to partners, registrars, and admins.

### 3.9. Campus Events, Fee Waivers, Notifications, and the Audit Ledger

Campus programs drive registration through events. An `Admin` creates a registry event with a `host_org_id` naming the host organization, a `title`, a free-text `venue`, a `starts_at`, an `ends_at` later than the start, and a `capacity` of at least 1. The host must be a partner organization of `org_type` `CAMPUS` (otherwise `ERR_EVENT_HOST_NOT_CAMPUS`, HTTP 422) and must be `ACTIVE` at creation time (otherwise `ERR_PARTNER_ORG_NOT_ACTIVE`). A new event begins in `DRAFT` with a `registered_count` of zero.

Publishing an event moves it from `DRAFT` to `PUBLISHED` and enforces a per-host scheduling rule: no other `PUBLISHED` event of the same host organization may have an overlapping window. Windows are half-open — an event occupies from its `starts_at` inclusive up to its `ends_at` exclusive — and two windows overlap only when the new event's start falls before the existing event's end and the existing event's start falls before the new event's end; windows that merely touch at an endpoint do not overlap. A violation fails with `ERR_EVENT_WINDOW_OVERLAP`.

From `PUBLISHED`, an admin completes the event once the current logical time has reached its `ends_at` — completing earlier fails with `ERR_EVENT_ENDED` — moving it to `COMPLETED`. Cancellation is defined from both non-terminal states but with different weights: cancelling a `DRAFT` event simply moves it to `CANCELLED`, while cancelling a `PUBLISHED` event cascades — every `BOOKED` registration moves to `CANCELLED`, the `registered_count` is recomputed to zero, the event's `version` increments, and every unused waiver code issued for the event becomes invalid, so a later attempt to spend one fails with `ERR_WAIVER_CODE_INVALID`.

Booking is the owner's side of the program. An owner books a seat at a `PUBLISHED` event (any other state fails with `ERR_EVENT_NOT_PUBLISHED`) while the current logical time is still before the event's `ends_at` (otherwise `ERR_EVENT_ENDED`). Two quota rules guard the door: the event's `registered_count` must still be below its `capacity` (a full event rejects with `ERR_EVENT_CAPACITY_FULL`, HTTP 422), and an owner may hold at most one `BOOKED` registration per event (a repeat booking rejects with `ERR_EVENT_REGISTRATION_EXISTS`). A successful booking creates the registration in `BOOKED` status with the acting owner recorded as `owner_id` and the event as `event_id`, mints a fee-waiver `waiver_code` for the booking with `waiver_used` initially false, increments the event's `registered_count` by 1, and increments the event's `version`. The seat invariant is exact and continuous: `registered_count` always equals the number of the event's registrations currently in `BOOKED` status and always stays within zero and `capacity` inclusive. Cancelling a booking — the compensating action, available to the registration's own owner while it is `BOOKED` — moves it to `CANCELLED`, decrements `registered_count` by 1, and increments the event's `version`; the event-cancellation cascade above is the bulk form of the same invariant, driving the count to zero. Waiver codes minted here are spent at bicycle registration (§3.2), where spending one flips `waiver_used` to true.

Event list views accept `host_org_id` and `status` filters; registration list views accept `event_id`, `owner_id`, and `status` filters, and an owner sees only their own registrations.

Two read models close the loop. Every notification the platform emits carries a `kind` — one of `MATCH_FOUND`, `CLAIM_APPROVED`, `CLAIM_REJECTED`, `TRANSFER_COMPLETED`, `TRANSFER_CANCELLED_STOLEN`, `REPORT_FLAGGED`, `BID_OUTBID`, or `AUCTION_WON` — and is stored with its recipient `owner_id`, a human-readable `message`, and a polymorphic pointer to the related object via `related_entity_type` and `related_entity_id` (plain labels, not foreign keys). A notification's `read` flag starts false; the owner marks their own notification read, which sets `read` to true and increments its `version`. Notification list views accept `owner_id` and `unread_only` filters, and an owner sees only their own notifications. The ledger, finally, is queryable by registrars and admins: ledger list views accept `owner_id`, `partner_org_id`, `auction_id`, `bicycle_id`, and `entry_type` filters, exposing the append-only financial record whose balancing invariant §2.8 defines.

## 4. Endpoint Definitions

Operations that create a new resource — registering an owner, onboarding a partner organization, registering a bicycle, initiating a transfer, filing a theft report, recording an intake, filing a claim, scheduling an auction, placing a bid, creating an event, booking a seat, or raising a duplicate flag — return `201 Created`. Operations that modify an existing resource, drive a state transition, or perform a read return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/registry/_clock/set_current_utc` | Set the server's logical clock | Admin |
| POST | `/registry/owners/register` | Self-register an owner account | Anonymous |
| GET | `/registry/owners/{id}` | Read an owner (an owner reads only itself) | Owner, Registrar, Admin |
| PATCH | `/registry/owners/{id}` | Update own profile fields | Owner |
| POST | `/registry/partner-orgs` | Onboard a partner organization in `PENDING` | Admin |
| GET | `/registry/partner-orgs` | List partner organizations | Registrar, Admin |
| GET | `/registry/partner-orgs/{id}` | Read a partner organization (a partner reads only its own) | Partner, Registrar, Admin |
| POST | `/registry/partner-orgs/{id}/activate` | Activate from `PENDING` or `SUSPENDED` | Admin |
| POST | `/registry/partner-orgs/{id}/suspend` | Suspend an `ACTIVE` organization | Admin |
| POST | `/registry/partner-orgs/{id}/revoke` | Revoke an `ACTIVE` or `SUSPENDED` organization (terminal) | Admin |
| POST | `/registry/bicycles` | Register a bicycle: fee computation, ledger posting, duplicate auto-scan, waiver consumption | Owner |
| GET | `/registry/bicycles` | List bicycles (owners see only their own; partners may search across all) | Owner, Partner, Registrar, Admin |
| GET | `/registry/bicycles/{id}` | Read a bicycle (owner: own only; partner: only while `STOLEN`) | Owner, Partner, Registrar, Admin |
| PATCH | `/registry/bicycles/{id}` | Update descriptive fields of an own bicycle (OCC-guarded) | Owner |
| POST | `/registry/transfers` | Initiate an ownership transfer / sale report | Owner |
| GET | `/registry/transfers` | List transfers (owners see only transfers they participate in) | Owner, Registrar, Admin |
| GET | `/registry/transfers/{id}` | Read a transfer (participant owners only) | Owner, Registrar, Admin |
| POST | `/registry/transfers/{id}/accept` | Buyer accepts: ownership moves, transfer fee posts | Owner |
| POST | `/registry/transfers/{id}/reject` | Buyer rejects | Owner |
| POST | `/registry/transfers/{id}/cancel` | Seller cancels a pending transfer | Owner |
| POST | `/registry/theft-reports` | File a theft report for an own bicycle | Owner |
| GET | `/registry/theft-reports` | List theft reports (owner: own; partner: `FLAGGED` only) | Owner, Partner, Registrar, Admin |
| GET | `/registry/theft-reports/{id}` | Read a theft report (owner: own; partner: only when `FLAGGED`) | Owner, Partner, Registrar, Admin |
| POST | `/registry/theft-reports/{id}/request-info` | Registrar requests more information | Registrar |
| POST | `/registry/theft-reports/{id}/respond` | Owner responds, returning the report to review | Owner |
| POST | `/registry/theft-reports/{id}/flag` | Registrar flags the report, cascading the bicycle to `STOLEN` | Registrar |
| POST | `/registry/theft-reports/{id}/reject` | Registrar rejects the report | Registrar |
| POST | `/registry/theft-reports/{id}/withdraw` | Owner withdraws the report, unwinding the flag when flagged | Owner |
| POST | `/registry/recovery-intakes` | Partner records a recovered-bicycle intake | Partner |
| GET | `/registry/recovery-intakes` | List intakes (partner: own organization's only) | Partner, Registrar, Admin |
| GET | `/registry/recovery-intakes/{id}` | Read an intake (partner: own organization's only) | Partner, Registrar, Admin |
| POST | `/registry/recovery-intakes/{id}/scan` | Score the intake against all `FLAGGED` reports, creating or refreshing match candidates | Partner, Registrar |
| POST | `/registry/recovery-intakes/{id}/mark-unclaimed` | Registrar marks the intake unclaimed after the thirty-day wait | Registrar |
| POST | `/registry/recovery-intakes/{id}/complete-return` | Partner confirms physical handoff to the approved claimant | Partner |
| GET | `/registry/matches` | List match candidates | Owner, Partner, Registrar, Admin |
| GET | `/registry/matches/{id}` | Read a match candidate | Owner, Partner, Registrar, Admin |
| POST | `/registry/matches/{id}/dismiss` | Registrar dismisses a `PROPOSED` or `NOTIFIED` match | Registrar |
| POST | `/registry/claims` | Owner claims a recovered bicycle via a `NOTIFIED` match | Owner |
| GET | `/registry/claims` | List claims (owner: own only) | Owner, Partner, Registrar, Admin |
| GET | `/registry/claims/{id}` | Read a claim (owner: own only) | Owner, Partner, Registrar, Admin |
| POST | `/registry/claims/{id}/approve` | Registrar approves, firing the match → intake → bicycle/report cascade | Registrar |
| POST | `/registry/claims/{id}/reject` | Registrar rejects with a reason | Registrar |
| POST | `/registry/claims/{id}/withdraw` | Owner withdraws their own `UNDER_REVIEW` claim | Owner |
| POST | `/registry/auctions` | Registrar schedules an auction for an `UNCLAIMED` intake | Registrar |
| GET | `/registry/auctions` | List auctions | Owner, Partner, Registrar, Admin |
| GET | `/registry/auctions/{id}` | Read an auction | Owner, Partner, Registrar, Admin |
| POST | `/registry/auctions/{id}/open` | Open bidding within the scheduled window | Registrar |
| POST | `/registry/auctions/{id}/close` | Close bidding and rank the field | Registrar |
| POST | `/registry/auctions/{id}/settle` | Settle: final waterfall, balanced ledger entries, intake disposed | Registrar |
| POST | `/registry/auctions/{id}/void-settlement` | Financially reverse a settlement via mirrored `REVERSAL` entries | Registrar |
| POST | `/registry/auctions/{id}/cancel` | Cancel from `SCHEDULED`, or from `OPEN` with zero bids | Registrar |
| POST | `/registry/auctions/{id}/bids` | Place a bid (OCC-guarded) | Owner |
| GET | `/registry/bids` | List bids (owner: own only) | Owner, Partner, Registrar, Admin |
| GET | `/registry/bids/{id}` | Read a bid (owner: own only) | Owner, Partner, Registrar, Admin |
| POST | `/registry/bids/{id}/retract` | Retract an own non-leading `ACTIVE` bid while the auction is `OPEN` | Owner |
| POST | `/registry/events` | Create a registration event hosted by an `ACTIVE` `CAMPUS` organization | Admin |
| GET | `/registry/events` | List events | Owner, Partner, Registrar, Admin |
| GET | `/registry/events/{id}` | Read an event | Owner, Partner, Registrar, Admin |
| POST | `/registry/events/{id}/publish` | Publish, enforcing per-host window non-overlap | Admin |
| POST | `/registry/events/{id}/complete` | Complete a `PUBLISHED` event once its window has ended | Admin |
| POST | `/registry/events/{id}/cancel` | Cancel, cascading bookings and invalidating unused waivers | Admin |
| POST | `/registry/events/{id}/registrations` | Owner books a seat, minting a fee-waiver code | Owner |
| GET | `/registry/event-registrations` | List event registrations (owner: own only) | Owner, Registrar, Admin |
| GET | `/registry/event-registrations/{id}` | Read an event registration (owner: own only) | Owner, Registrar, Admin |
| POST | `/registry/event-registrations/{id}/cancel` | Owner cancels their own `BOOKED` registration | Owner |
| POST | `/registry/duplicate-flags` | Manually flag a suspect duplicate pair | Partner, Registrar |
| GET | `/registry/duplicate-flags` | List duplicate flags | Partner, Registrar, Admin |
| GET | `/registry/duplicate-flags/{id}` | Read a duplicate flag | Partner, Registrar, Admin |
| POST | `/registry/duplicate-flags/{id}/confirm` | Registrar confirms: loser merges, survivor clears | Registrar |
| POST | `/registry/duplicate-flags/{id}/dismiss` | Registrar dismisses: both bicycles return to `CLEAR` | Registrar |
| GET | `/registry/ledger-entries` | List append-only ledger entries | Registrar, Admin |
| GET | `/registry/ledger-entries/{id}` | Read a ledger entry | Registrar, Admin |
| GET | `/registry/notifications` | List notifications (owner: own only) | Owner, Registrar, Admin |
| GET | `/registry/notifications/{id}` | Read a notification (owner: own only) | Owner, Registrar, Admin |
| POST | `/registry/notifications/{id}/mark-read` | Owner marks their own notification read | Owner |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED_ROLE` | 403 |
| `ERR_FORBIDDEN_RESOURCE_ACCESS` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_OWNER_NOT_FOUND` | 404 |
| `ERR_PARTNER_ORG_NOT_FOUND` | 404 |
| `ERR_BICYCLE_NOT_FOUND` | 404 |
| `ERR_TRANSFER_NOT_FOUND` | 404 |
| `ERR_THEFT_REPORT_NOT_FOUND` | 404 |
| `ERR_RECOVERY_INTAKE_NOT_FOUND` | 404 |
| `ERR_MATCH_NOT_FOUND` | 404 |
| `ERR_CLAIM_NOT_FOUND` | 404 |
| `ERR_AUCTION_NOT_FOUND` | 404 |
| `ERR_BID_NOT_FOUND` | 404 |
| `ERR_EVENT_NOT_FOUND` | 404 |
| `ERR_EVENT_REGISTRATION_NOT_FOUND` | 404 |
| `ERR_DUPLICATE_FLAG_NOT_FOUND` | 404 |
| `ERR_NOTIFICATION_NOT_FOUND` | 404 |
| `ERR_PARTNER_ORG_NOT_ACTIVE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_BICYCLE_NOT_TRANSFERABLE` | 409 |
| `ERR_BICYCLE_MERGED` | 409 |
| `ERR_TRANSFER_NOT_PENDING` | 409 |
| `ERR_THEFT_REPORT_NOT_ACTIONABLE` | 409 |
| `ERR_RECOVERY_NOT_ACTIONABLE` | 409 |
| `ERR_MATCH_NOT_OPEN` | 409 |
| `ERR_CLAIM_NOT_REVIEWABLE` | 409 |
| `ERR_AUCTION_NOT_OPEN` | 409 |
| `ERR_AUCTION_NOT_CLOSABLE` | 409 |
| `ERR_AUCTION_NOT_SETTLABLE` | 409 |
| `ERR_BID_NOT_RETRACTABLE` | 409 |
| `ERR_EVENT_NOT_PUBLISHED` | 409 |
| `ERR_FLAG_NOT_OPEN` | 409 |
| `ERR_DUPLICATE_HOLD` | 409 |
| `ERR_DUPLICATE_SERIAL_ACTIVE` | 409 |
| `ERR_TRANSFER_ALREADY_PENDING` | 409 |
| `ERR_SELF_TRANSFER` | 422 |
| `ERR_REPORT_ALREADY_OPEN` | 409 |
| `ERR_EVENT_HOST_NOT_CAMPUS` | 422 |
| `ERR_EVENT_WINDOW_OVERLAP` | 409 |
| `ERR_AUCTION_ALREADY_EXISTS` | 409 |
| `ERR_AUCTION_WINDOW_CONFLICT` | 409 |
| `ERR_AUCTION_HAS_BIDS` | 409 |
| `ERR_INTAKE_HAS_ACTIVE_MATCH` | 409 |
| `ERR_CLAIM_ALREADY_EXISTS` | 409 |
| `ERR_EVENT_REGISTRATION_EXISTS` | 409 |
| `ERR_WAIVER_CODE_INVALID` | 422 |
| `ERR_TRANSFER_EXPIRED` | 409 |
| `ERR_AUCTION_NOT_YET_OPEN` | 409 |
| `ERR_AUCTION_WINDOW_EXPIRED` | 409 |
| `ERR_DISPOSITION_TOO_EARLY` | 409 |
| `ERR_EVENT_ENDED` | 409 |
| `ERR_BID_BELOW_MINIMUM` | 422 |
| `ERR_EVENT_CAPACITY_FULL` | 422 |
