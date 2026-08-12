# Aircraft Title, Escrow & Registration Service API — Product Requirements Document

## 1. Introduction

The Aircraft Title, Escrow & Registration Service is an Oklahoma City title and escrow agent's operations platform. It coordinates the full life of an aircraft purchase file — title search and lien discovery, escrow funding and disbursement instructions, FAA registry filings and International Registry priority, deregistration and export certificates, lien release coordination with lenders, closing document signature logistics, owner-trustee structures, and post-closing recording verification.

The platform exists because aircraft closings are unforgiving of procedural error. A lien paid off one day past its quote window can unwind a closing. A deregistration submitted while a lien remains outstanding invites registry rejection and personal liability. A trustee without citizenship evidence on file renders an entire ownership structure defective. The system therefore treats the closing as a state machine with strictly ordered gates: liens must be released before funds can flow, funds must be present before closing, closing must occur before filings can be submitted, and filings must be accepted before the file can be called recorded. Wherever two writers could race a shared aggregate — deposits, disbursement drafting, close — the API applies optimistic concurrency control on the parent file so a writer always acts on the version of the file it actually observed.

This document is the product contract for the engineers implementing the API. §2 lays out system-wide specifications; §3 walks the business workflows in narrative form; §4 and §5 tabulate the endpoint and error catalogues.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which names their operational capacity. The system recognizes four roles — `EscrowOfficer`, `EscrowManager`, `LenderRep`, and `Auditor` — and those spellings are contractual. A request missing either header, or presenting a role the system does not know, is rejected with `ERR_UNAUTHENTICATED`. A request whose role is known but is not on the endpoint's authorized list is rejected with `ERR_UNAUTHORIZED_ROLE`.

Each role's identity semantics are contractual and determine what `X-User-ID` is compared against:

- When `X-User-Role` is `EscrowOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example, as `created_by_user_id` on a `DisbursementInstruction` when an officer drafts one) but does not compare it to any entity's `id`.
- When `X-User-Role` is `EscrowManager`, `X-User-ID` is likewise opaque. It is recorded as `approved_by_user_id` when the manager approves a disbursement, and is compared against that instruction's `created_by_user_id` only to enforce segregation of duties — it is never resolved against a persisted entity.
- When `X-User-Role` is `LenderRep`, `X-User-ID` is the `id` of the acting `Party` (whose `party_type` must be `LENDER` in context). Quoting or confirming receipt of a lien release compares the lien's `lienor_party_id` against `X-User-ID`; a mismatch is rejected with `ERR_FORBIDDEN_IDENTITY`.
- When `X-User-Role` is `Auditor`, `X-User-ID` is opaque. The role has read-only reach across the API and authors nothing.

`EscrowOfficer` runs the day-to-day file: registering aircraft, opening files, ordering searches, recording deposits, drafting filings and documents, and coordinating releases. `EscrowManager` approves money movement, accepts or rejects trust agreements, and operates the logical clock. `LenderRep` exists only to quote payoffs and confirm receipt of release documents on its own liens. `Auditor` reads everything and writes nothing.

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

Request validation is strict wherever an endpoint defines body fields: a body that is not a JSON object, a missing required field, a field the endpoint does not define, or a value failing type, range, enumeration, or `YYYY-MM-DD` date validation is rejected with `ERR_INVALID_REQUEST` (HTTP 400). An absent or unparsable body is treated as an empty object. Endpoints that define no body fields (for example hold, resume, cancel, dispute, approve, and the other bodiless transition actions) ignore any body presented; the clock-set endpoint of §2.4 reads only `to_iso8601` and ignores any additional fields.

### 2.3. Pagination

List endpoints accept two query parameters, both optional. `limit` bounds the number of items returned; it defaults to 10 and is clamped into the inclusive range 1–100 — a value below 1 is treated as 1, a value above 100 as 100, and a value that does not parse as an integer falls back to the default. `offset` skips that many items from the start of the result set; it defaults to 0, a negative value is treated as 0, and a value that does not parse as an integer falls back to the default. Unless otherwise specified, list endpoints return resources sorted by `created_at` ascending; ties on `created_at` preserve insertion (creation) order.

List endpoints also accept exact-match query filters on selected resource fields, combined conjunctively: `/api/escrow-files` filters on `aircraft_id`, `buyer_party_id`, `seller_party_id`, `lender_party_id`, `trustee_party_id`, and `status`; `/api/liens` on `escrow_file_id`, `aircraft_id`, `title_search_id`, `lienor_party_id`, and `status`; `/api/deposits` on `escrow_file_id`, `payer_party_id`, and `status`; `/api/disbursements` on `escrow_file_id`, `payee_party_id`, `lien_id`, and `status`; `/api/filings` on `escrow_file_id`, `aircraft_id`, `filing_type`, and `status`; and `/api/trust-agreements` on `aircraft_id`, `trustee_party_id`, and `status`.

List responses populate the `meta` envelope with four pagination fields: `limit`, `offset`, `total_count`, and `has_more`. `total_count` is the size of the full filtered result set before pagination; `has_more` is true when `offset + limit < total_count`.

### 2.4. Logical Clock and Lifecycle Sweeps

All time inside the system runs on a server-held logical clock, not the wall clock. At process start the logical clock reads exactly `2026-05-01T00:00:00Z`, and the server never falls back to wall-clock time thereafter. Only an `EscrowManager` may advance the logical clock, by supplying a `to_iso8601` instant through the clock-set capability described in §4. Advancing the clock returns the new instant in `current_utc`. The supplied instant is accepted as given — the server performs no monotonicity check, so the logical clock may be set to an instant earlier than its current value. A missing or unparsable `to_iso8601` is rejected with `ERR_INVALID_REQUEST`.

Advancing the clock triggers three lifecycle sweeps, each evaluated against the new logical instant. A `TitleSearch` in `COMPLETED` whose `effective_at` lies strictly more than 30 days in the past transitions to `STALE`. A `LienRelease` in `QUOTED` whose `good_through_date` is strictly earlier than the new logical date transitions to `QUOTE_EXPIRED`. A `TrustAgreement` in `ACCEPTED` whose `expiry_date` is strictly earlier than the new logical date transitions to `EXPIRED`. After the sweeps, the posture of every affected `EscrowFile` is recomputed. The sweep is the only path into `STALE`, `QUOTE_EXPIRED`, and `EXPIRED`; no client-facing endpoint sets these states directly.

### 2.5. Common Resource Properties

Every top-level resource in the system — `Aircraft`, `Party`, `EscrowFile`, `TrustAgreement`, `TitleSearch`, `Lien`, `LienRelease`, `Deposit`, `DisbursementInstruction`, `Filing`, and `ClosingDocument` — carries a standard set of system-managed fields:

- `id` (string): a server-minted UUID. It carries no type prefix and is never reused.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, fixed at the moment of creation.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource.
- `version` (integer): starts at 1 and increments by exactly 1 on every mutation of the resource.

Most resources additionally expose a `status` field whose enumeration and transitions are defined per entity in §3 — `Aircraft` uses `registry_status` instead, and `Filing` carries a parallel `verification_status` alongside its lifecycle `status`.

Every state transition, every cascade side effect that mutates a resource, and every recomputation of a computed field counts as a mutation of that resource and therefore refreshes its `updated_at` and increments its `version`. The `EscrowFile`'s `version` in particular is the pivot of the OCC rules in §2.7.

### 2.6. Nested Resource Retrieval and Path Resolution

When a request path contains multiple identifiers — for example, an action on a deposit, disbursement, document, filing, or title search scoped beneath `/api/escrow-files/{id}/...` — identifiers are resolved left to right. The first identifier that fails to resolve, or whose resolved child does not in fact belong to the resolved parent, terminates the request with `ERR_NOT_FOUND`. A request naming a non-existent escrow file therefore fails with `ERR_NOT_FOUND` before the server ever inspects the child identifier, regardless of whether that child would have resolved.

### 2.7. Optimistic Concurrency Control on the Escrow File

Three write operations require the client to present its last observed version of the parent `EscrowFile` as a non-optional request field named `expected_escrow_file_version`: recording a deposit against the file, drafting a disbursement instruction against the file, and closing the file. In each case, the presented value is compared against the file's current `version`; if another writer has advanced the file since the client last read it, the request is rejected with `ERR_STALE_VERSION` (HTTP 412), and no mutation is applied. The deposit-write and disbursement-write variants of this rule exist because funding math and disbursement drafting must be evaluated against the version of the file the client actually saw; the close variant exists because closing freezes money fields and must not apply to a state the closer never observed. Endpoints not in this list do not accept a version field; because request bodies are strictly validated (§2.2), presenting one to an endpoint with defined body fields is rejected with `ERR_INVALID_REQUEST`, not ignored. On the deposit and disbursement writes, body-field validation and the existence of referenced resources are checked before the version comparison; on close, the version comparison runs immediately after body validation and before the posture, document-completeness, and search-freshness preconditions of §3.10.

### 2.8. Money, Precision, and Frozen Computations

All monetary amounts are integer cents. No floating-point values ever appear in money fields, and there are no decimal-place rules because there are no decimals — every computation lands on an integer cent. Where a calculation internally requires rounding, it rounds half-up to the nearest cent.

Two figures are computed at file creation and frozen onto the `EscrowFile` forever after: `proration_amount_cents` and `escrow_fee_cents`. The evaluation order is pinned — proration first, then the fee computed against the sum of `purchase_price_cents` and the just-frozen proration — so that the fee base itself never includes the fee. The buyer's `buyer_amount_due_cents` is frozen alongside them as `purchase_price_cents + proration_amount_cents + escrow_fee_cents`. Three further figures — `total_funded_cents`, `escrow_balance_cents`, and `seller_net_proceeds_cents` — remain live for the life of the file and are recomputed on every deposit create or return and on every disbursement release or void. At file creation they initialize to `total_funded_cents` = 0, `escrow_balance_cents` = 0, and `seller_net_proceeds_cents` = `purchase_price_cents` + `proration_amount_cents` − `escrow_fee_cents`. Closing the file freezes the live figures as of the closing instant.

### 2.9. Escrow Posture and Cascading Consistency

Every `EscrowFile` carries a computed `posture` drawn from `READY`, `LIEN_BLOCKED`, `TRUST_BLOCKED`, and `LIEN_AND_TRUST_BLOCKED`. Posture is never written directly; it is derived from the states of the file's liens and from any applicable trust agreement. A file's posture is `LIEN_BLOCKED` when any of its liens is in `DISCOVERED`, `DISPUTED`, or `RELEASE_PENDING`. When the file's `requires_trust` flag is true, the posture is `TRUST_BLOCKED` unless an `ACCEPTED` `TrustAgreement` covers the aircraft with a term that covers the present logical date — `effective_date` on or before it and `expiry_date` on or after it, both ends inclusive. When both conditions hold simultaneously the posture is `LIEN_AND_TRUST_BLOCKED`. The posture becomes `READY` only when neither condition holds.

Posture is recomputed on every event that could change it: lien discovery, dispute, dispute-resolution, release voiding, release recording, trust acceptance, and trust expiry. When a recompute flips a file in `SEARCH_COMPLETE` to `READY`, the file automatically bubbles up to `CLEARED`. When a file in `CLEARED` subsequently has `total_funded_cents` at or above `buyer_amount_due_cents`, it automatically transitions to `FUNDED`. These two cascades mean a single lien-record event can, in one atomic step, walk a file from `SEARCH_COMPLETE` through `CLEARED` to `FUNDED` without any further client action.

Cancellation is the broadest cascade in the system. Cancelling a file returns every `RECEIVED` deposit to `RETURNED` (stamping `returned_at` to the logical instant), voids every `PENDING_APPROVAL` or `APPROVED` disbursement, withdraws every `QUEUED` or `REJECTED` filing, voids every non-terminal lien release, returns any `RELEASE_PENDING` lien that no longer has an active release to `DISCOVERED`, and releases the aircraft for use by other files. Each of those mutations refreshes the affected resource's `updated_at` and increments its `version` independently.

## 3. Business Logic & Workflows

### 3.1. Onboarding Aircraft and Parties

Before any file can open, the aircraft and the transaction's parties must exist in the system. An `EscrowOfficer` registers an `Aircraft` by providing its `n_number`, `serial_number`, `make_model`, `year`, and an optional `is_international_registry` flag. The `n_number` must be unique across all registered aircraft; a duplicate is rejected with `ERR_DUPLICATE_N_NUMBER`. The `year` must lie between 1900 and 2100 inclusive. `is_international_registry` defaults to `false` when omitted and marks the airframe as eligible for Cape Town International Registry interests — a marker that later determines whether `IR_INTEREST` liens may be recorded against it. A newly registered aircraft begins life with `registry_status` set to `REGISTERED`.

An `EscrowOfficer` creates a `Party` with a `party_type` of `BUYER`, `SELLER`, `LENDER`, or `TRUSTEE`, plus a `legal_name`. An `email` may be supplied but is optional. The `is_citizenship_verified` flag defaults to `false` and is load-bearing only for trustees: a `TrustAgreement` cannot be submitted unless its trustee party's `is_citizenship_verified` is `true`. A lender party's `id` is what a `LenderRep` later presents as `X-User-ID` when acting on that lender's liens.

### 3.2. Opening the Escrow File

An `EscrowOfficer` opens an `EscrowFile` by naming the `aircraft_id`, the `buyer_party_id`, and the `seller_party_id`. Optional `lender_party_id` and `trustee_party_id` fields attach a funding lender and an owner-trustee respectively; either may be omitted. Every referenced id must resolve to an existing resource — the aircraft, the buyer, the seller, and (when present) the lender and trustee — or the open is rejected with `ERR_NOT_FOUND`; the server does not check the `party_type` of the named parties. The `requires_trust` flag defaults to `false` and must be set `true` when ownership will vest in an owner trustee — it gates the posture rule described in §2.9. The commercial terms come in as `purchase_price_cents` (strictly positive), `annual_registration_fee_cents` (non-negative), a `proration_method` of `DAILY` or `MONTHLY`, and an `expected_close_date` in `YYYY-MM-DD` form.

The server then computes and freezes the three contract figures in pinned order. First, the proration at `expected_close_date` is computed per §3.2.1 below and frozen into `proration_amount_cents`. Second, the escrow fee is computed against the base of `purchase_price_cents + proration_amount_cents` per §3.2.2 and frozen into `escrow_fee_cents`. Third, `buyer_amount_due_cents` is frozen as the sum of those three components. Posture is initialized at this point; a file whose `requires_trust` is `true` and for which no `ACCEPTED` trust covers the aircraft on the open date will be born `TRUST_BLOCKED`, and the converse for lien discovery.

An aircraft may be the subject of at most one non-terminal file at a time. An attempt to open a file for an aircraft that already has another file whose status is not `CANCELLED` or `VERIFIED` is rejected with `ERR_AIRCRAFT_UNDER_CONTRACT`. The new file starts in `OPENED`.

#### 3.2.1. Closing Proration

Proration reimburses the seller for the post-closing portion of the annual registration fee. The `proration_method` selects one of two variants.

Under the `DAILY` variant, count the whole days strictly after `expected_close_date` through December 31 of the same calendar year, inclusive of December 31. The proration is the annual fee multiplied by that day count and divided by 365, rounded half-up to the nearest cent in a single final rounding. A closing on December 31 yields zero days and therefore a zero proration.

Under the `MONTHLY` variant, count the calendar months strictly after the month containing `expected_close_date` through December — call that count the full months. Each full month contributes the annual fee divided by 12, rounded half-up to the nearest cent. If the day of the month of `expected_close_date` is on or before the 15th, the closing month also contributes a half-month credit of the annual fee divided by 24, rounded half-up to the nearest cent. The proration is the sum of those per-month and half-month roundings — never the other way around. A closing on December 20 yields zero full months and, because the 20th is after the 15th, no half-month credit, for a total of zero.

#### 3.2.2. Escrow Fee Schedule

The escrow fee is a three-tier basis-point schedule applied to the base of `purchase_price_cents + proration_amount_cents`. The first tier covers the portion of the base up to and including $500,000 (that is, 50,000,000 cents) and is charged at 30 basis points. The second tier covers the portion of the base strictly above $500,000 and up to and including $2,000,000 (that is, 200,000,000 cents) and is charged at 20 basis points. The third tier covers any portion of the base strictly above $2,000,000 and is charged at 10 basis points. Each tier's amount is rounded half-up to the nearest cent independently, and the three rounded tier amounts are then summed.

The summed figure is then floored at a minimum fee of $1,500 (150,000 cents). If the file's `requires_trust` is `true`, a flat trust surcharge of $750 (75,000 cents) is added. The result is capped at a maximum fee of $25,000 (2,500,000 cents). The final figure is frozen into `escrow_fee_cents` at file creation and is never recomputed.

### 3.3. Title Search and Lien Discovery

Once a file is open, an `EscrowOfficer` orders a title search. The new `TitleSearch` begins in `ACTIVE`, and the parent's transition from `OPENED` to `SEARCH_ORDERED` happens automatically on the first successful order. Ordering is permitted while the file is in `OPENED`, `SEARCH_ORDERED`, `SEARCH_COMPLETE`, `CLEARED`, `FUNDED`, `CLOSED`, or `RECORDED`. At most one search per file may be in `ACTIVE` or in a non-stale `COMPLETED` state at a time; an attempt to order while such a search exists is rejected with `ERR_SEARCH_ALREADY_ACTIVE`. A `STALE` search, by contrast, never blocks a new order.

Completing a search is the act that discovers liens. An `EscrowOfficer` completes an `ACTIVE` search by submitting a `findings` array; the array may be empty, completing the search with `finding_count` zero and discovering no liens. Each entry names a `lienor_party_id` (which must reference an existing `Party` — a missing party is rejected with `ERR_NOT_FOUND` — whose `party_type` is `LENDER`, with an existing non-`LENDER` party rejected as `ERR_INVALID_REQUEST`), a `lienor_name`, an `amount_cents` strictly greater than zero, a `lien_type` of `FAA_RECORDED`, `IR_INTEREST`, `STATE`, or `JUDGMENT`, and a `filed_at` in `YYYY-MM-DD` form. When the `lien_type` is `IR_INTEREST`, an `ir_registered_at` date in `YYYY-MM-DD` form is required; for the other types it is omitted by convention and not required by the server. Completing the search stamps both `effective_at` and `completed_at` to the current logical instant, sets `finding_count` to the number of findings entries, and creates one `Lien` in `DISCOVERED` per findings entry, in array order. Each created lien copies `escrow_file_id` and `aircraft_id` from the parent file, references the search as `title_search_id`, and carries the lienor details and `original_amount_cents` from the finding. Lien priority ranks are then recomputed per §3.3.1. Completion also advances a `SEARCH_ORDERED` parent to `SEARCH_COMPLETE` and recomputes the file's posture — so a search that surfaces a `DISCOVERED` lien leaves the file `LIEN_BLOCKED`, while a clean search leaves it `READY` and may immediately bubble the file to `CLEARED` (and, if funds already cover `buyer_amount_due_cents`, onward to `FUNDED`).

A completed search remains fresh through the exact instant `effective_at` plus 30 days. The moment the logical clock reads an instant strictly later than `effective_at` plus 30 days, the sweep described in §2.4 transitions the search to `STALE`. An `EscrowOfficer` may refresh a `STALE` search back to `ACTIVE`; refreshing stamps a new `effective_at` to the current logical instant but does not alter `finding_count` or the previously stamped `completed_at`, and does not disturb any lien previously created — prior liens persist untouched.

#### 3.3.1. Lien Priority Ranking

Payoff priority across an aircraft's liens is a strict, deterministic ordering, recomputed whenever a lien is created for that aircraft. All liens whose `aircraft_id` matches participate, regardless of status, whether still active or already released. The ordering walks three classes. Class 1 holds liens whose `lien_type` is `IR_INTEREST`, ordered by `ir_registered_at` ascending — earliest International Registry registration wins. Class 2 holds `FAA_RECORDED` liens, ordered by `filed_at` ascending. Class 3 holds `STATE` and `JUDGMENT` liens together, also ordered by `filed_at` ascending. The classes concatenate with class 1 first, then class 2, then class 3; within a class, ties on the date break by the lien's `created_at` ascending. The `priority_rank` on each lien is its 1-based position in that concatenation. A lien's `id` is never used as a tie-break.

### 3.4. Lien Release Coordination

A discovered lien must be released before the file can clear. The release workflow runs on a separate `LienRelease` resource so that multiple payoff attempts against the same lien can be tracked over time.

An `EscrowOfficer` requests release coordination on a `DISCOVERED` lien. The new `LienRelease` begins in `REQUESTED`, and the lien automatically transitions from `DISCOVERED` to `RELEASE_PENDING`. A release cannot be requested while another release on the same lien is in `QUOTED` with a quote window — the closed interval from `quote_date` through `good_through_date`, inclusive on both ends — that still covers today's logical date; that attempt is rejected with `ERR_QUOTE_WINDOW_OPEN`. This quote-window check is evaluated before the lien-state requirement: since a lien carrying such a `QUOTED` release is necessarily in `RELEASE_PENDING` at that moment, the rejection in that situation is always `ERR_QUOTE_WINDOW_OPEN`, never the generic invalid-transition error.

A `LenderRep` then submits a payoff quote, but only when `X-User-ID` equals the lien's `lienor_party_id`; any other identity is rejected with `ERR_FORBIDDEN_IDENTITY`. The quote names a `payoff_basis` of `FLAT` or `PER_DIEM`, a `quoted_payoff_cents` (a strictly positive integer), and a `good_through_date`. When `payoff_basis` is `PER_DIEM`, a strictly positive integer `per_diem_cents` is required; when the basis is `FLAT`, `per_diem_cents` must be omitted, and supplying it is rejected with `ERR_INVALID_REQUEST`. Quoting stamps `quote_date` to the current logical date and transitions the release from `REQUESTED` to `QUOTED`.

With a quote in hand, the same `LenderRep` confirms the signed release document has been received, moving the release from `QUOTED` to `RELEASE_RECEIVED`. An `EscrowOfficer` then files the release with the registry (`RELEASE_RECEIVED` to `FILED`) and, once the registry confirms, records it (`FILED` to `RECORDED`). Recording is gated on the logical date being on or before `good_through_date`, inclusive — a `QUOTED` release whose window has already passed will already have been swept to `QUOTE_EXPIRED` and the transition does not exist; the sweep touches only `QUOTED` releases, so a `FILED` release whose window has since passed is not swept, and an attempt to record it is rejected with `ERR_INVALID_TRANSITION`.

Recording is the moment the effective payoff freezes onto the lien. For a `FLAT` quote, the effective payoff is simply `quoted_payoff_cents`, regardless of the record date. For a `PER_DIEM` quote, the effective payoff is `quoted_payoff_cents` plus `per_diem_cents` multiplied by the number of whole days elapsed between `quote_date` and the record date, but capped so the elapsed-day count never exceeds the number of whole days between `quote_date` and `good_through_date`, and floored so it never drops below zero (a record date earlier than `quote_date` contributes zero per-diem days). The frozen payoff becomes the lien's `amount_paid_cents`; the lien's `outstanding_cents` becomes `original_amount_cents` minus `amount_paid_cents`. The lien transitions from `RELEASE_PENDING` to `RELEASED`, the file's posture is recomputed, and a file in `SEARCH_COMPLETE` whose posture flips to `READY` automatically bubbles to `CLEARED` — and from there to `FUNDED` if the funding threshold is already met.

A release may be voided by an `EscrowOfficer` at any time while it is in `REQUESTED`, `QUOTED`, `RELEASE_RECEIVED`, or `FILED`. A `QUOTED` release whose `good_through_date` falls strictly behind the logical date is swept to `QUOTE_EXPIRED`. Either path — `VOIDED` or `QUOTE_EXPIRED` — leaves the lien without an active release, and a `RELEASE_PENDING` lien in that position returns automatically to `DISCOVERED`, recomputing posture as it goes.

### 3.5. Funding the File

Funds arrive as `Deposit` records created by an `EscrowOfficer` against the file. Each deposit names a `payer_party_id` (which must reference an existing `Party`, otherwise the write is rejected with `ERR_NOT_FOUND`), an `amount_cents` strictly greater than zero, a `purpose` of `EARNEST_MONEY`, `BUYER_FUNDS`, or `LENDER_FUNDS`, and the OCC guard `expected_escrow_file_version` (see §2.7). Deposits may be recorded while the file is in `OPENED`, `SEARCH_ORDERED`, `SEARCH_COMPLETE`, `CLEARED`, or `FUNDED`.

A new deposit lands in `RECEIVED`. Its arrival triggers two recomputations: `total_funded_cents` becomes the sum of `amount_cents` across all `RECEIVED` deposits on the file, and `escrow_balance_cents` becomes that total minus the sum of `amount_cents` across all `RELEASED` disbursements on the file. If the file was `CLEARED` and the new `total_funded_cents` is greater than or equal to `buyer_amount_due_cents` — equality counts — the file transitions to `FUNDED` automatically. The deposit-write also increments the file's `version` by 1, which is why the OCC field exists.

A deposit in `RECEIVED` may be returned by an `EscrowOfficer`, but only while the parent file is pre-closing — that is, not in `CLOSED`, `RECORDED`, `VERIFIED`, or `CANCELLED`. Returning stamps `returned_at` to the logical instant, transitions the deposit to `RETURNED`, and recomputes `total_funded_cents` and `escrow_balance_cents` with the returned row now excluded. If the file was `FUNDED` and the return drops `total_funded_cents` strictly below `buyer_amount_due_cents`, the file automatically reverts from `FUNDED` to `CLEARED`.

### 3.6. Disbursement Instructions and Segregation of Duties

Payouts from escrow are drafted as `DisbursementInstruction` records. Drafting is open to either an `EscrowOfficer` or an `EscrowManager`, and lands the instruction in `PENDING_APPROVAL`. The drafter supplies a `payee_party_id` (which must reference an existing `Party`, otherwise `ERR_NOT_FOUND`), an `amount_cents` strictly greater than zero, a `purpose` of `LIEN_PAYOFF`, `SELLER_PROCEEDS`, `ESCROW_FEE`, `TAX_REMITTANCE`, or `OTHER`, and the OCC guard `expected_escrow_file_version`. When `purpose` is `LIEN_PAYOFF`, a `lien_id` must also be supplied, and it must reference a lien belonging to the same file — a `lien_id` that does not resolve, or that resolves to a lien of another file, is rejected with `ERR_NOT_FOUND`; for any other purpose, `lien_id` must be omitted, and supplying one is rejected with `ERR_INVALID_REQUEST`. Drafting is permitted while the file is in `SEARCH_COMPLETE`, `CLEARED`, `FUNDED`, `CLOSED`, or `RECORDED`. The server stamps `created_by_user_id` with the drafter's `X-User-ID` and increments the file's `version` by 1.

Approval is reserved to an `EscrowManager`. Segregation of duties is enforced structurally: the approver's `X-User-ID` must differ from the instruction's `created_by_user_id`, and an approval attempted by the drafter is rejected with `ERR_SEGREGATION_OF_DUTIES`. A successful approval stamps `approved_by_user_id` and moves the instruction from `PENDING_APPROVAL` to `APPROVED`.

Release is the fiscal gate. An `EscrowManager` releases an `APPROVED` instruction, but only while the parent file is in `CLOSED` or `RECORDED`, and only when three checks pass. First, the instruction's `amount_cents` must not exceed the file's current `escrow_balance_cents` — equality is allowed, so an exact-zero balance is reachable; a shortfall is rejected with `ERR_ESCROW_SHORTFALL`. Second, when the purpose is `LIEN_PAYOFF`, the referenced lien must be in `RELEASED`; otherwise the release is rejected with `ERR_LIEN_NOT_RELEASED`. Third, when the purpose is `LIEN_PAYOFF`, the instruction's `amount_cents` must equal the lien's frozen `amount_paid_cents` exactly; a mismatch is rejected with `ERR_PAYOFF_MISMATCH`. A successful release moves the instruction to `RELEASED` and recomputes the file's `escrow_balance_cents` and `seller_net_proceeds_cents`. The seller's net figure is `purchase_price_cents + proration_amount_cents - escrow_fee_cents`, minus the sum of `RELEASED` disbursements whose purpose is `LIEN_PAYOFF`, minus the sum of `RELEASED` disbursements whose purpose is `TAX_REMITTANCE`. The closing-statement read returns this live figure alongside the frozen components; the statement body carries exactly seven fields: `purchase_price_cents`, `proration_amount_cents`, `escrow_fee_cents`, `buyer_amount_due_cents`, `total_funded_cents`, `escrow_balance_cents`, and `seller_net_proceeds_cents`.

An instruction in `PENDING_APPROVAL` or `APPROVED` may be voided by an `EscrowManager`, moving it to `VOIDED`. A `VOIDED` instruction's amount never contributes to `escrow_balance_cents` or `seller_net_proceeds_cents`.

### 3.7. Owner-Trust Agreements

When ownership will vest in a non-citizen structure, an `EscrowOfficer` drafts a `TrustAgreement` naming the `aircraft_id`, the `trustee_party_id` (which must reference a `Party` whose `party_type` is `TRUSTEE` — a missing aircraft or trustee is rejected with `ERR_NOT_FOUND`, and an existing trustee reference whose `party_type` is not `TRUSTEE` is rejected with `ERR_INVALID_REQUEST`), the `beneficiary_name`, a `beneficiary_citizenship` of `US_CITIZEN` or `NON_US_CITIZEN`, an `effective_date`, and an `expiry_date`. The `effective_date` must be strictly earlier than `expiry_date`; otherwise creation is rejected with `ERR_INVALID_DATE_RANGE`. A new agreement begins in `DRAFT`.

Submitting the agreement requires that the trustee's `is_citizenship_verified` is `true`; otherwise the submit is rejected with `ERR_TRUSTEE_NOT_QUALIFIED`. A successful submit stamps `submitted_at` to the logical instant and moves the agreement from `DRAFT` to `SUBMITTED`.

Acceptance is an `EscrowManager` action and carries the trust-overlap guard: there must be no other `ACCEPTED` `TrustAgreement` for the same aircraft whose `[effective_date, expiry_date]` interval strictly overlaps the candidate's interval. Touching endpoints — one agreement's `expiry_date` equal to another's `effective_date` — are permitted and do not constitute overlap. A violation is rejected with `ERR_TRUST_OVERLAP`. Acceptance moves the agreement from `SUBMITTED` to `ACCEPTED` and recomputes posture on every `EscrowFile` for the same aircraft whose `requires_trust` is `true`. An `EscrowManager` may instead reject the agreement, moving it to `REJECTED`; an `EscrowOfficer` may then revise a `REJECTED` agreement back to `DRAFT`, optionally supplying replacement `effective_date` and `expiry_date` values. When only one of the two dates is supplied, the other keeps its stored value and the merged pair must again satisfy `effective_date` strictly earlier than `expiry_date`; every revise clears `submitted_at`, whether or not dates were supplied.

An `ACCEPTED` agreement whose `expiry_date` falls strictly behind the logical date is swept to `EXPIRED` by the clock, and the posture of every affected file is recomputed — a file relying on that trust becomes `TRUST_BLOCKED` at that moment.

### 3.8. Closing Documents and Signature Logistics

Closing documents are tracked per file. An `EscrowOfficer` adds a `ClosingDocument` while the file is in `SEARCH_COMPLETE`, `CLEARED`, or `FUNDED`, naming a `doc_type` of `PURCHASE_AGREEMENT`, `ESCROW_INSTRUCTIONS`, `BILL_OF_SALE_DOC`, `WIRE_AUTHORIZATION`, or `CLOSING_STATEMENT`, and a `required_signer_party_ids` array. Every entry in `required_signer_party_ids` must be one of the file's named parties — the buyer, the seller, the lender if present, or the trustee if present; an entry that is not is rejected with `ERR_SIGNER_NOT_PARTY`. The array may be empty; such a document can never reach `FULLY_SIGNED`, since every presented signer falls outside the required set. The new document begins in `PREPARED` with an empty `signed_party_ids` array. Adding a document increments the file's `version` by 1.

Sending the document for signature moves it from `PREPARED` to `OUT_FOR_SIGNATURE`. Signatures are then collected one at a time: an `EscrowOfficer` records a signature by presenting a `signer_party_id`. Signatures are recorded only while the document is in `OUT_FOR_SIGNATURE` or `PARTIALLY_SIGNED`; an attempt against a document in any other status — `PREPARED`, or the terminal `FULLY_SIGNED` — is rejected with `ERR_INVALID_TRANSITION`, and this status gate is evaluated before the signer-level checks below, so a duplicate signature presented against an already `FULLY_SIGNED` document yields `ERR_INVALID_TRANSITION`, not `ERR_ALREADY_SIGNED`. The signer must be a member of `required_signer_party_ids` — a signer outside the required set is rejected with `ERR_SIGNER_NOT_REQUIRED` — and must not already appear in `signed_party_ids`, since duplicates are rejected with `ERR_ALREADY_SIGNED`. The first valid signature moves the document from `OUT_FOR_SIGNATURE` to `PARTIALLY_SIGNED` and appends the signer to `signed_party_ids`. Subsequent valid signatures that do not complete the set keep the document in `PARTIALLY_SIGNED` and continue to append. The signature that completes the required set — meaning that after appending, the `signed_party_ids` set equals the `required_signer_party_ids` set — moves the document from either `OUT_FOR_SIGNATURE` or `PARTIALLY_SIGNED` to `FULLY_SIGNED`. `FULLY_SIGNED` is terminal.

### 3.9. Registry Filings and Post-Closing Verification

Filings represent the paper the registry actually sees. An `EscrowOfficer` queues a `Filing` while the file is in `CLEARED`, `FUNDED`, `CLOSED`, or `RECORDED`, naming a `filing_type` of `BILL_OF_SALE`, `REGISTRATION_APPLICATION`, `MORTGAGE_RECORDATION`, `DEREGISTRATION`, or `EXPORT_CERTIFICATE`. The new filing lands in `QUEUED`, its `aircraft_id` copied from the parent file, and its `verification_status` initialized to `NONE`. A file may hold at most one non-`WITHDRAWN` filing per `filing_type`; an attempt to queue a duplicate is rejected with `ERR_DUPLICATE_FILING`.

Submitting a queued filing is gated by the file being in `CLOSED` or `RECORDED`, and by a strict prerequisite chain on the same file. A `REGISTRATION_APPLICATION` may be submitted only when the file's `BILL_OF_SALE` filing is `ACCEPTED`. A `MORTGAGE_RECORDATION` requires the file's `REGISTRATION_APPLICATION` to be `ACCEPTED`. A `DEREGISTRATION` requires the file's `BILL_OF_SALE` to be `ACCEPTED` — and additionally requires that every lien of the file be in `RELEASED` (otherwise the submit is rejected with `ERR_LIENS_OUTSTANDING`) and that the aircraft's `registry_status` currently be `REGISTERED` (a miss there is rejected with `ERR_FILING_SEQUENCE_VIOLATION`; the lien check is evaluated before the registry-status check). An `EXPORT_CERTIFICATE` requires the file's `DEREGISTRATION` to be `ACCEPTED`. A prerequisite miss on any of these is rejected with `ERR_FILING_SEQUENCE_VIOLATION`. A successful submit stamps `submitted_at` to the logical instant, assigns `sequence_index` to the count of successful submit operations — initial submits and resubmissions — ever performed on the file, including this one, starting at 1, and — when the filing is a `DEREGISTRATION` — moves the aircraft's `registry_status` from `REGISTERED` to `DEREGISTRATION_PENDING`. The filing itself transitions from `QUEUED` to `SUBMITTED`.

Acceptance is recorded by an `EscrowOfficer` presenting the registry's `confirmation_code`. The filing transitions from `SUBMITTED` to `ACCEPTED`, `registry_confirmation_code` is stored, and `verification_status` moves from `NONE` to `PENDING`. Aircraft side effects chain off acceptance: accepting a `DEREGISTRATION` moves the aircraft from `DEREGISTRATION_PENDING` to `DEREGISTERED`, and accepting an `EXPORT_CERTIFICATE` moves it from `DEREGISTERED` to `EXPORTED`. Acceptance also triggers the file-level bubble-ups — a `CLOSED` file whose `BILL_OF_SALE` and `REGISTRATION_APPLICATION` are now both `ACCEPTED` moves to `RECORDED`, and a `RECORDED` file with no filing in `SUBMITTED` or `REJECTED` and every `ACCEPTED` filing at `verification_status` `MATCHED` moves to `VERIFIED`.

Rejection is recorded by an `EscrowOfficer` presenting a `reason`; the filing transitions from `SUBMITTED` to `REJECTED` and `reject_reason` is stored. A rejected filing may be resubmitted by an `EscrowOfficer`. Resubmission is gated by the same file-state requirement as an initial submit (the file must be in `CLOSED` or `RECORDED`) and re-evaluates the same prerequisite chain at resubmit time — including, for a `DEREGISTRATION`, the lien and registry-status gates — so a filing whose prerequisite was accepted while it sat in `REJECTED` may now go through. On success it refreshes `submitted_at`, reassigns `sequence_index`, clears `reject_reason`, and returns the filing to `SUBMITTED`.

Post-closing recording verification compares what the registry actually recorded against what was accepted. An `EscrowOfficer` verifies a filing by presenting a `recorded_confirmation_code`. If it equals the filing's stored `registry_confirmation_code`, `verification_status` moves to `MATCHED`; otherwise it moves to `MISMATCHED`. Verification is permitted from `PENDING` and again from `MISMATCHED`, so a mismatched filing can be re-verified once the underlying discrepancy is reconciled. Every verification re-runs the file-level `VERIFIED` bubble-up check described above.

### 3.10. Close, Hold, Cancel, and the End of the File

Closing is the pivot event of the file's life. An `EscrowOfficer` closes a `FUNDED` file by presenting `expected_escrow_file_version` matching the file's current `version`. Four preconditions are then evaluated. The file's `posture` must be `READY`; otherwise the close is rejected with `ERR_POSTURE_NOT_READY`. Every `ClosingDocument` on the file must be in `FULLY_SIGNED` — a file with zero documents trivially satisfies this; any document short of `FULLY_SIGNED` yields `ERR_DOCUMENTS_INCOMPLETE`. The file's latest `TitleSearch` — the most recently created one — must be in `COMPLETED` and still fresh, meaning the current logical instant is on or before `effective_at` plus 30 days, inclusive; a stale or missing search is rejected with `ERR_SEARCH_STALE`. And the OCC check of §2.7 must pass — it is evaluated first of these four, immediately after body validation and before the posture, document, and search checks. A successful close stamps `closed_at` to the logical instant, freezes the live money figures, transitions the file from `FUNDED` to `CLOSED`, and increments the file's `version` by 1.

Holding is the routine interrupt. An `EscrowOfficer` places a file in `OPENED`, `SEARCH_ORDERED`, `SEARCH_COMPLETE`, `CLEARED`, or `FUNDED` on hold; the prior status is stored in `hold_return_state` and the file moves to `ON_HOLD`. While a file is `ON_HOLD`, every mutation scoped beneath the file — title search completion, lien actions, releases, deposits, disbursements, filings, documents — and the close action are rejected with `ERR_FILE_ON_HOLD`, as is an attempt to hold the file again. An `EscrowOfficer` resumes an `ON_HOLD` file, which restores the status stored in `hold_return_state` and clears that field back to null.

Cancelling is the terminal interrupt. An `EscrowOfficer` cancels a file in `OPENED`, `SEARCH_ORDERED`, `SEARCH_COMPLETE`, `CLEARED`, `FUNDED`, or `ON_HOLD`, moving it to `CANCELLED`, clearing any `hold_return_state` back to null, and triggering the broad cascade described in §2.9. Once a file reaches `CANCELLED` or `VERIFIED`, every mutation against it or anything scoped beneath it — including hold, resume, cancel, and close — is rejected with `ERR_ALREADY_TERMINAL`.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource or add a new resource to a collection return `201 Created`. Operations that modify an existing resource return `200 OK`. All endpoints are mounted under `/api`. A request to an undefined path, or to a defined path with an unsupported method, is rejected with `ERR_NOT_FOUND` (404).

| Method | Path                                              | Description                                                                                                                              | Authorized Role(s)                              |
| ------ | ------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------- |
| POST   | `/api/_clock/set_current_utc`                     | Advance the logical clock; runs staleness sweeps                                                                                          | EscrowManager                                   |
| POST   | `/api/aircraft`                                   | Register a subject aircraft                                                                                                               | EscrowOfficer                                   |
| GET    | `/api/aircraft/{id}`                              | Get aircraft                                                                                                                              | EscrowOfficer, EscrowManager, LenderRep, Auditor |
| GET    | `/api/aircraft/{id}/trust-agreements`             | List trust agreements covering the aircraft                                                                                               | EscrowOfficer, EscrowManager, LenderRep, Auditor |
| POST   | `/api/parties`                                    | Create a transaction party                                                                                                                | EscrowOfficer                                   |
| GET    | `/api/parties/{id}`                               | Get party                                                                                                                                 | EscrowOfficer, EscrowManager, LenderRep, Auditor |
| POST   | `/api/escrow-files`                               | Open an escrow file; computes and freezes fee, proration, and amount due                                                                  | EscrowOfficer                                   |
| GET    | `/api/escrow-files`                               | List escrow files                                                                                                                         | EscrowOfficer, EscrowManager, LenderRep, Auditor |
| GET    | `/api/escrow-files/{id}`                          | Get escrow file                                                                                                                           | EscrowOfficer, EscrowManager, LenderRep, Auditor |
| POST   | `/api/escrow-files/{id}/hold`                     | Place an active file on hold                                                                                                              | EscrowOfficer                                   |
| POST   | `/api/escrow-files/{id}/resume`                   | Resume an on-hold file to its stored return state                                                                                         | EscrowOfficer                                   |
| POST   | `/api/escrow-files/{id}/cancel`                   | Cancel a pre-closing file and cascade                                                                                                     | EscrowOfficer                                   |
| POST   | `/api/escrow-files/{id}/close`                    | Close a funded file (OCC-guarded)                                                                                                         | EscrowOfficer                                   |
| GET    | `/api/escrow-files/{id}/statement`                | Read the computed closing statement                                                                                                       | EscrowOfficer, EscrowManager, LenderRep, Auditor |
| POST   | `/api/escrow-files/{id}/title-searches`           | Order a title search                                                                                                                      | EscrowOfficer                                   |
| POST   | `/api/title-searches/{id}/complete`               | Complete a search with findings                                                                                                           | EscrowOfficer                                   |
| POST   | `/api/title-searches/{id}/refresh`                | Refresh a stale search back to active                                                                                                     | EscrowOfficer                                   |
| GET    | `/api/escrow-files/{id}/title-searches`           | List searches for a file                                                                                                                  | EscrowOfficer, EscrowManager, LenderRep, Auditor |
| GET    | `/api/liens`                                      | List liens                                                                                                                                | EscrowOfficer, EscrowManager, LenderRep, Auditor |
| GET    | `/api/liens/{id}`                                 | Get lien                                                                                                                                  | EscrowOfficer, EscrowManager, LenderRep, Auditor |
| POST   | `/api/liens/{id}/dispute`                         | Dispute a discovered lien                                                                                                                 | EscrowOfficer                                   |
| POST   | `/api/liens/{id}/resolve-dispute`                 | Return a disputed lien to discovered                                                                                                      | EscrowOfficer                                   |
| POST   | `/api/liens/{id}/releases`                        | Request lien release coordination                                                                                                         | EscrowOfficer                                   |
| GET    | `/api/liens/{id}/releases`                        | List releases for a lien                                                                                                                  | EscrowOfficer, EscrowManager, LenderRep, Auditor |
| POST   | `/api/releases/{id}/quote`                        | Lender submits payoff quote                                                                                                               | LenderRep                                       |
| POST   | `/api/releases/{id}/receive-release`              | Lender confirms signed release received                                                                                                   | LenderRep                                       |
| POST   | `/api/releases/{id}/file`                         | Officer files the release with the registry                                                                                               | EscrowOfficer                                   |
| POST   | `/api/releases/{id}/record`                       | Officer confirms registry recordation; freezes effective payoff                                                                            | EscrowOfficer                                   |
| POST   | `/api/releases/{id}/void`                         | Void a non-terminal release                                                                                                               | EscrowOfficer                                   |
| POST   | `/api/escrow-files/{id}/deposits`                 | Record incoming escrow funds (OCC-guarded)                                                                                                | EscrowOfficer                                   |
| POST   | `/api/deposits/{id}/return`                       | Return a received deposit pre-closing                                                                                                     | EscrowOfficer                                   |
| GET    | `/api/deposits`                                   | List deposits                                                                                                                             | EscrowOfficer, EscrowManager, LenderRep, Auditor |
| GET    | `/api/deposits/{id}`                              | Get deposit                                                                                                                               | EscrowOfficer, EscrowManager, LenderRep, Auditor |
| POST   | `/api/escrow-files/{id}/disbursements`            | Draft a disbursement instruction (OCC-guarded)                                                                                            | EscrowOfficer, EscrowManager                    |
| POST   | `/api/disbursements/{id}/approve`                 | Manager approves (segregation of duties enforced)                                                                                         | EscrowManager                                   |
| POST   | `/api/disbursements/{id}/release`                 | Release approved funds                                                                                                                    | EscrowManager                                   |
| POST   | `/api/disbursements/{id}/void`                    | Void a non-released instruction                                                                                                           | EscrowManager                                   |
| GET    | `/api/disbursements`                              | List disbursement instructions                                                                                                            | EscrowOfficer, EscrowManager, LenderRep, Auditor |
| GET    | `/api/disbursements/{id}`                         | Get disbursement instruction                                                                                                              | EscrowOfficer, EscrowManager, LenderRep, Auditor |
| POST   | `/api/escrow-files/{id}/filings`                  | Queue a registry filing                                                                                                                   | EscrowOfficer                                   |
| POST   | `/api/filings/{id}/submit`                        | Submit a queued filing to the registry                                                                                                    | EscrowOfficer                                   |
| POST   | `/api/filings/{id}/accept`                        | Record registry acceptance with its confirmation code                                                                                     | EscrowOfficer                                   |
| POST   | `/api/filings/{id}/reject`                        | Record registry rejection                                                                                                                 | EscrowOfficer                                   |
| POST   | `/api/filings/{id}/resubmit`                      | Resubmit a rejected filing (prerequisites re-evaluated)                                                                                   | EscrowOfficer                                   |
| POST   | `/api/filings/{id}/verify`                        | Post-closing recording verification                                                                                                       | EscrowOfficer                                   |
| GET    | `/api/filings`                                    | List filings                                                                                                                              | EscrowOfficer, EscrowManager, LenderRep, Auditor |
| GET    | `/api/filings/{id}`                               | Get filing                                                                                                                                | EscrowOfficer, EscrowManager, LenderRep, Auditor |
| POST   | `/api/trust-agreements`                           | Draft an owner-trust agreement                                                                                                            | EscrowOfficer                                   |
| POST   | `/api/trust-agreements/{id}/submit`               | Submit trust for approval                                                                                                                 | EscrowOfficer                                   |
| POST   | `/api/trust-agreements/{id}/accept`               | Accept trust (overlap check)                                                                                                              | EscrowManager                                   |
| POST   | `/api/trust-agreements/{id}/reject`               | Reject trust                                                                                                                              | EscrowManager                                   |
| POST   | `/api/trust-agreements/{id}/revise`               | Revise a rejected trust back to draft                                                                                                     | EscrowOfficer                                   |
| GET    | `/api/trust-agreements`                           | List trust agreements                                                                                                                     | EscrowOfficer, EscrowManager, LenderRep, Auditor |
| GET    | `/api/trust-agreements/{id}`                      | Get trust agreement                                                                                                                       | EscrowOfficer, EscrowManager, LenderRep, Auditor |
| POST   | `/api/escrow-files/{id}/documents`                | Add a closing document with its required signer set                                                                                       | EscrowOfficer                                   |
| POST   | `/api/documents/{id}/send`                        | Send document for signature                                                                                                               | EscrowOfficer                                   |
| POST   | `/api/documents/{id}/sign`                        | Record one party's signature                                                                                                              | EscrowOfficer                                   |
| GET    | `/api/escrow-files/{id}/documents`                | List closing documents of a file                                                                                                          | EscrowOfficer, EscrowManager, LenderRep, Auditor |

## 5. Error Code Catalogue

| Error ID                    | HTTP Status Code |
| --------------------------- | ---------------- |
| `ERR_UNAUTHENTICATED`       | 401              |
| `ERR_UNAUTHORIZED_ROLE`     | 403              |
| `ERR_FORBIDDEN_IDENTITY`    | 403              |
| `ERR_INVALID_REQUEST`       | 400              |
| `ERR_NOT_FOUND`             | 404              |
| `ERR_FILE_ON_HOLD`          | 409              |
| `ERR_ALREADY_TERMINAL`      | 409              |
| `ERR_INVALID_TRANSITION`    | 409              |
| `ERR_STALE_VERSION`         | 412              |
| `ERR_SEGREGATION_OF_DUTIES` | 403              |
| `ERR_TRUSTEE_NOT_QUALIFIED` | 422              |
| `ERR_DUPLICATE_N_NUMBER`    | 409              |
| `ERR_AIRCRAFT_UNDER_CONTRACT` | 409            |
| `ERR_SEARCH_ALREADY_ACTIVE` | 409              |
| `ERR_SEARCH_STALE`          | 409              |
| `ERR_QUOTE_WINDOW_OPEN`     | 409              |
| `ERR_TRUST_OVERLAP`         | 409              |
| `ERR_INVALID_DATE_RANGE`    | 422              |
| `ERR_DUPLICATE_FILING`      | 409              |
| `ERR_FILING_SEQUENCE_VIOLATION` | 409          |
| `ERR_LIENS_OUTSTANDING`     | 409              |
| `ERR_SIGNER_NOT_PARTY`      | 422              |
| `ERR_SIGNER_NOT_REQUIRED`   | 422              |
| `ERR_ALREADY_SIGNED`        | 409              |
| `ERR_POSTURE_NOT_READY`     | 409              |
| `ERR_DOCUMENTS_INCOMPLETE`  | 409              |
| `ERR_LIEN_NOT_RELEASED`     | 409              |
| `ERR_ESCROW_SHORTFALL`      | 422              |
| `ERR_PAYOFF_MISMATCH`       | 422              |
