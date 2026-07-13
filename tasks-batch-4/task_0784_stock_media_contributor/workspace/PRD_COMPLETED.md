# Stock-Media Contributor Platform API — Product Requirements Document

## 1. Introduction

This document specifies the backend API for a stock-media contributor platform in the style of Shutterstock or Getty. The platform is the operational spine that carries a piece of media from the moment a photographer, videographer, or illustrator registers as a contributor, through content review and acceptance, licensing sales to buyers, career-earnings accumulation, and finally cash disbursement — all while enforcing the trust-and-safety, intellectual-property, and tax obligations that a marketplace of this kind must satisfy.

Four distinct professional perspectives meet inside the system. Contributors create and curate the catalog: they onboard, submit tax paperwork, obtain model and property releases, upload assets with descriptive metadata, and eventually withdraw the money they have earned. Content reviewers guard catalog quality by claiming and adjudicating each submission. Compliance officers own the legal surface — verifying releases and tax forms and ruling on takedown claims. Finance administrators run the commercial and monetary machinery: they define license pricing, record sales, settle and occasionally reverse earnings, issue corrective adjustments, and process payouts. Because a single sale touches royalty rates, exclusivity status, career tiers, and tax withholding at once, the platform must treat money as a strictly conserved ledger and must lock the economics of each transaction at the instant it happens.

The requirements below define the entities, their lifecycles, the calculations that price each sale and each payout, and the validation rules that keep the marketplace honest. Monetary values are always expressed and stored in integer cents, and every stateful mutation is versioned so that concurrent finance operations cannot silently overwrite one another.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request other than contributor self-registration must be authenticated by two HTTP headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming the principal's role. If either header is absent, or if `X-User-Role` is not one of the four roles defined below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are well-formed but the named role is not permitted to perform the requested operation (per the endpoint table in §4), the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The platform recognizes exactly four roles, spelled exactly as follows:

- **`Contributor`** — the media creator, responsible for onboarding, uploads, metadata, model releases, tax forms, exclusivity windows, and payout requests.
- **`Reviewer`** — the content reviewer, who claims submitted assets and records accept/reject decisions.
- **`ComplianceOfficer`** — trust, safety, and legal, who verifies releases and tax forms and files and adjudicates takedown requests.
- **`FinanceAdmin`** — finance and operations, who manages license tiers, records sales as downloads, settles and reverses earnings, posts earning adjustments, processes payouts, and controls the logical clock.

The `Contributor` role is **entity-backed**: when `X-User-Role` is `Contributor`, `X-User-ID` is the `id` of the acting `Contributor` record. Ownership checks on any resource that references a contributor compare that resource's `contributor_id` — resolved transitively through the owning asset where the resource references an `asset_id` — to `X-User-ID`. A `Contributor` that attempts to mutate a resource it does not own is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403).

The other three roles are **opaque operator identities**. When `X-User-Role` is `Reviewer`, `ComplianceOfficer`, or `FinanceAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`. The server may record such an identifier where a workflow calls for it — for example, the deciding reviewer's `X-User-ID` is stored as `reviewer_id` on the `AssetReview` it produces — but it never treats that value as an entity primary key.

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

List endpoints accept two optional query parameters, `limit` and `offset`. The `limit` parameter defaults to 10, may be no less than 1, and may be no greater than 100. The `offset` parameter defaults to 0 and has a minimum of 0. Every list endpoint returns its rows sorted by `created_at` in ascending order (oldest first); because the logical clock advances only when explicitly set, rows that share the same `created_at` are common and are further ordered among themselves by the sequence in which they were created (insertion order). The `meta` block of a list response carries the `limit` and `offset` in effect, the `total_count` of matching rows before pagination, and a `has_more` boolean that is true when rows remain beyond the current page.

### 2.4. Common Resource Properties

Unless a specific entity is called out below as an exception, every resource carries four server-managed common properties. `id` is a server-minted UUID with no type prefix. `created_at` is the ISO 8601 UTC timestamp (three fractional digits) at which the resource was created. `updated_at` is the ISO 8601 UTC timestamp of the most recent mutation. `version` is an integer that starts at 1 on creation and increments by exactly 1 on every mutation of that resource; it is the concurrency token described in §2.6.

The `AssetReview` entity is the sole exception: it is an immutable audit record and therefore carries only `id` and `created_at`. It has neither `updated_at` nor `version`, because once written it is never mutated.

All timestamps that the platform accepts as input or emits — `created_at`, `updated_at`, `start_at`, `end_at`, `hold_start`, `hold_end`, `available_at`, and the clock value — are ISO 8601 UTC.

### 2.5. The Logical Clock

All time-dependent behavior is governed by a **logical clock** rather than wall-clock time. On server startup the clock reads exactly `2026-03-01T00:00:00Z`; before any clock-setting call is made it holds this default and never falls back to real-world time. A finance administrator may advance (or set) the clock by supplying a `to_iso8601` instant; the endpoint returns the new clock value as `current_utc`. Earnings clearing, exclusivity coverage, and takedown hold intervals are all evaluated against the current logical clock, so tests drive time forward explicitly through this capability. Moreover, every server-assigned timestamp — each resource's `created_at` and `updated_at`, each computed `available_at`, `hold_start`, and `hold_end`, and each response's `api_request_timestamp` — is read from this logical clock rather than from wall-clock time, so the clock's current value is exactly the instant stamped on anything created or mutated while it holds that value.

### 2.6. Monetary Precision and Optimistic Concurrency

All monetary amounts — sale prices, royalty amounts, balances, withholding, and payout totals — are stored and returned as integer **cents**; no fractional cents ever exist. Whenever a rate is multiplied against a cent amount, the product is rounded to the nearest whole cent using **round half up** (a result whose fractional part is exactly one half rounds away from zero, upward). Royalty rates and treaty rates are exact decimal fractions (for example, a rate of `0.15` means fifteen percent).

Requesting a payout is guarded by **optimistic concurrency control** on the payee contributor. Because a payout drains the contributor's entire available balance, the request body normally carries `expected_contributor_version`, the `version` of the target `Contributor` that the client last observed. When the field is omitted entirely, the server performs no version comparison and proceeds. When it is present, the server compares this value against the contributor's current `version`. If they do not match (including when the supplied value is not an integer at all) — meaning some other operation (a prior payout, an earnings settlement, a reversal, or an adjustment) has advanced the contributor's `version` since the client last read it — the request is rejected with `ERR_STALE_CONTRIBUTOR_VERSION` (HTTP 412) before any balance arithmetic is performed, so the client can never overwrite state it has not seen. No other endpoint takes a version field.

### 2.7. The Earnings Ledger and Its Conservation

Two running totals on each contributor form a conserved ledger. `lifetime_earnings_cents` is the career-earnings total; it starts at 0, is never negative, is credited when a download settles and by any positive earning adjustment, and is debited when a settled (AVAILABLE) download is later reversed. It never counts earnings that are still pending or that have been reversed. `available_balance_cents` is the subset of funds currently eligible for payout; it starts at 0, rises on settlement and on positive adjustments, and falls when a settled download is reversed and when a payout locks funds. The available balance may go temporarily negative only through a post-payout clawback (a settled download reversed after its earnings were already paid out). Every credit has a matching compensating debit, so a reversal always undoes exactly the amount its settlement credited.

### 2.8. Nested Path Resolution and Referential Integrity

Endpoints whose URL addresses a resource by `id`, and endpoints that carry foreign-key references in their body, resolve every named resource before applying any business rule. Path identifiers are validated left to right; a body foreign key such as `asset_id`, `contributor_id`, `model_release_id`, `similar_to_asset_id`, or `license_tier_code` is validated after the path. Any unresolved identifier yields `ERR_NOT_FOUND` (HTTP 404).

### 2.9. Validation Ordering

When several checks apply to one request, they are evaluated in a fixed precedence so that the returned error is deterministic. Authentication (`ERR_UNAUTHENTICATED`, 401) is checked first, then authorization (`ERR_UNAUTHORIZED`, 403), then existence of every path resource and body foreign key (`ERR_NOT_FOUND`, 404), then contributor resource-ownership (`ERR_NOT_RESOURCE_OWNER`, 403), then the payout stale-version check (`ERR_STALE_CONTRIBUTOR_VERSION`, 412), then whether the target resource is in a state from which the requested transition is defined (`ERR_INVALID_STATE`, 409). Below these come the domain-specific safety and business checks: suspension gating (`ERR_CONTRIBUTOR_SUSPENDED`, 403), the accept-time contributor-active check (`ERR_CONTRIBUTOR_NOT_ACTIVE`, 409), the accept-time release-verified check (`ERR_RELEASE_NOT_VERIFIED`, 422), exclusivity overlap (`ERR_EXCLUSIVITY_OVERLAP`, 409), the takedown hold-buffer check (`ERR_TAKEDOWN_HOLD_CONFLICT`, 409), the similar-reject distance check (`ERR_NOT_SIMILAR_ENOUGH`, 422), then generic field/format validation (`ERR_VALIDATION`, 422), and finally the two fiscal checks: the payout threshold (`ERR_BELOW_PAYOUT_THRESHOLD`, 422) and the clearing check (`ERR_NOT_YET_CLEARED`, 409). Earlier checks take precedence over later ones, so a request that would fail several rules surfaces the highest-priority failure.

## 3. Business Logic & Workflows

### 3.1. Contributor Onboarding and Tax Verification

A media creator joins the platform by self-registering, the one operation that requires no authentication headers. Registration supplies a `display_name` (a non-empty public name of at most 120 characters) and a `country_code` (two uppercase letters denoting the ISO 3166-1 alpha-2 country of tax residence, where `US` is treated as domestic and every other value as foreign). The new `Contributor` is created in `onboarding_status` `PENDING` with every computed field at its default: `tax_form_status` `MISSING`, `exclusivity` `NON_EXCLUSIVE`, `royalty_level` `BRONZE`, `lifetime_earnings_cents` 0, `available_balance_cents` 0, `accepted_asset_count` 0, and `strike_count` 0. The `X-User-ID` a contributor uses on subsequent calls is the `id` returned by this registration.

A pending contributor cannot earn acceptance of assets until tax onboarding completes. The contributor submits a tax form carrying `form_type` — `W9` for US persons or `W8BEN` for foreign persons — together with a non-empty opaque `tax_id`. A `W8BEN` filer may additionally supply a `treaty_rate_pct`, a foreign withholding treaty rate that, when present, must lie between 0.00 and 0.30 inclusive; the field is ignored for a `W9` and, when omitted for a `W8BEN`, is treated as the default foreign rate described in §3.7. Submitting a tax form creates it in `status` `SUBMITTED`, sets the contributor's `tax_form_status` to `SUBMITTED`, and increments the contributor's `version` by 1.

A compliance officer then decides the form, supplying a `decision` of either `VERIFY` or `REJECT`. Verifying a form that is `SUBMITTED` moves that form to `VERIFIED`, sets the contributor's `tax_form_status` to `VERIFIED`, and — if the contributor is still `PENDING` — advances the contributor's `onboarding_status` from `PENDING` to `ACTIVE`; both the tax form's `version` and the contributor's `version` increment by 1. Rejecting a `SUBMITTED` form requires a `reject_reason`, one of `INVALID_ID`, `MISMATCH`, or `INCOMPLETE`; the reason is stored on the form, the form moves to `REJECTED`, and the contributor's `tax_form_status` becomes `REJECTED` (both versions increment by 1). A decision on a form that is not `SUBMITTED` is rejected with `ERR_INVALID_STATE`, and a reject decision that omits `reject_reason` is rejected with `ERR_MISSING_REJECT_REASON`. A contributor may list its own tax forms; compliance officers and finance administrators may read them as well.

### 3.2. Model and Property Releases

Whenever an asset depicts a recognizable person or a recognizable piece of private property, the contributor must first obtain a release. A contributor creates a release with a `release_type` of `MODEL` (a recognizable person) or `PROPERTY` (recognizable private property) and a non-empty `releaser_name` naming the model or property owner who granted it. The release is created in `status` `PENDING`.

A compliance officer adjudicates the release with a `decision`. Verifying a `PENDING` release moves it to `VERIFIED`; rejecting a `PENDING` release requires a `reject_reason` — one of `ILLEGIBLE`, `UNSIGNED`, or `EXPIRED` — which is stored before the release moves to `REJECTED`. A decision on a release that is not `PENDING` is rejected with `ERR_INVALID_STATE`, and a reject without `reject_reason` yields `ERR_MISSING_REJECT_REASON`. A contributor may list its own releases; compliance officers may read them. The release matters at asset-acceptance time, as §3.3 describes.

### 3.3. Asset Upload, Metadata, and the Review Lifecycle

A contributor uploads an asset by creating it in `status` `DRAFT`. The creation payload names the owning contributor via `contributor_id` and supplies a non-empty `title` of at most 200 characters, a `media_type` of `PHOTO`, `VIDEO`, or `VECTOR`, a `content_category` of `COMMERCIAL` (licensable for advertising) or `EDITORIAL` (news and documentary use), a `keywords` array of between 1 and 50 non-empty search strings, and a `perceptual_hash`. The perceptual hash is a fixed-length lowercase hexadecimal string of an even number of characters between 4 and 16; all assets compared against one another share equal hash length. When the asset shows a recognizable subject, the contributor sets `requires_release` to true (it defaults to false) and links the governing release through `model_release_id`; that field is null when no release is required. While an asset sits in `DRAFT` or `REJECTED`, its owner may edit `title`, `keywords`, and `perceptual_hash`.

When the metadata is ready, the contributor submits the asset for review, advancing it from `DRAFT` to `SUBMITTED`. Submission requires that `keywords` be non-empty and, when `requires_release` is true, that `model_release_id` be set — a submission of a release-requiring asset with no `model_release_id` is rejected with `ERR_RELEASE_REQUIRED`. Submission is also one of the two operations blocked while the contributor is suspended (see §3.8): a submission by a `SUSPENDED` contributor is rejected with `ERR_CONTRIBUTOR_SUSPENDED`. An asset that has previously been rejected can re-enter review through the same submission action — a `REJECTED` asset returns to `SUBMITTED`, and on this resubmission the asset's `reject_reason` is cleared. This `REJECTED → SUBMITTED` revision loop is the only cyclic edge in the asset lifecycle; the same release-presence precondition applies on resubmission. Any submission attempt from a state other than `DRAFT` or `REJECTED` is rejected with `ERR_INVALID_STATE`.

A reviewer claims a `SUBMITTED` asset, advancing it from `SUBMITTED` to `IN_REVIEW`; claiming an asset that is not `SUBMITTED` yields `ERR_INVALID_STATE`. The reviewer then records a decision, which forks the lifecycle. On `ACCEPT`, the asset advances from `IN_REVIEW` to `ACCEPTED`: an `AssetReview` audit record with `decision` `ACCEPT` is created (stamped with the deciding reviewer's `reviewer_id`), the owning contributor's `accepted_asset_count` increases by 1, and both the asset's `version` and the contributor's `version` increment by 1. Acceptance carries two cross-entity preconditions. First, the owning contributor's `onboarding_status` must be `ACTIVE`; if it is not, acceptance is rejected with `ERR_CONTRIBUTOR_NOT_ACTIVE`. Second, when the asset's `requires_release` is true, the referenced `ModelRelease` must be in `status` `VERIFIED`; otherwise acceptance is rejected with `ERR_RELEASE_NOT_VERIFIED`.

Rejection is the divergent branch. On `REJECT`, the asset moves from `IN_REVIEW` to `REJECTED`: an `AssetReview` record with `decision` `REJECT` is created capturing the `reject_reason`, and the asset's `reject_reason` is set while its `version` increments by 1. Unlike acceptance, rejection leaves `accepted_asset_count` untouched and does not increment the contributor's `version`. A reject `decision` must carry a `reject_reason` — one of `QUALITY`, `SIMILAR`, `METADATA`, or `MISSING_RELEASE` — and a reject that omits it is rejected with `ERR_MISSING_REJECT_REASON`. A decision on an asset that is not `IN_REVIEW` yields `ERR_INVALID_STATE`. In both the accept and reject branches the endpoint responds with the newly created `AssetReview` record (HTTP 201) rather than with the mutated asset.

The `SIMILAR` sub-branch has additional structure. When `reject_reason` is `SIMILAR`, the reviewer must name the earlier accepted asset the submission collides with via `similar_to_asset_id`; a `SIMILAR` reject without it is rejected with `ERR_MISSING_SIMILAR_TARGET`. The referenced asset must itself be `ACCEPTED`, and the two assets must be perceptually close: the platform computes the number of differing bits between the two equal-length hexadecimal `perceptual_hash` values (the Hamming distance — the count of one-bits in the bitwise exclusive-or of the two hashes interpreted as integers). A `SIMILAR` reject is valid only when that distance is at most 5; a distance of exactly 5 still qualifies as similar, while a distance of 6 or more does not, in which case the reject is refused with `ERR_NOT_SIMILAR_ENOUGH`. The `similar_to_asset_id` reference is recorded on the `AssetReview`. Reviews may be listed and filtered by their `asset_id` or by `similar_to_asset_id`, and a single `AssetReview` may be read by its `id`; contributors, reviewers, and compliance officers may read them. Assets themselves may be listed and filtered by `contributor_id`, `model_release_id`, and `status`.

### 3.4. License Tiers, Sales, and the Royalty Snapshot

A finance administrator defines the sale catalog as a set of license tiers. Each `LicenseTier` has a `code` — one of `STANDARD`, `ENHANCED`, `EXTENDED`, or `EDITORIAL`, unique across all tiers so that a duplicate code is rejected with `ERR_VALIDATION` — and a `base_price_cents`, the buyer's sale price at that tier, which must be at least 1. Any role may read the tier list.

A sale is recorded as a download against an accepted asset. The finance administrator supplies the `asset_id` of the licensed asset, which must be in `status` `ACCEPTED` at download time, the selected `license_tier_code`, and a non-empty opaque `buyer_reference`. Creation snapshots the commercial terms onto the new `Download` and can never be re-derived afterward: `sale_price_cents` is copied from the selected tier's `base_price_cents`; `royalty_rate_snapshot_pct` is locked by the royalty-rate calculation below using the contributor's `exclusivity` and `royalty_level` **as they stand at that instant**; `royalty_amount_cents` is the contributor's locked earning, computed as `sale_price_cents` multiplied by `royalty_rate_snapshot_pct`, rounded to the nearest whole cent using round half up. The download begins in `earning_status` `PENDING`, and its `available_at` — the earliest instant its earning may settle — is set to the download's `created_at` plus a clearing period of 30 days.

The royalty rate is chosen from a matrix indexed by the contributor's exclusivity status and career royalty level at download time. The base rate is read from this matrix:

| Royalty level | `NON_EXCLUSIVE` base rate | `EXCLUSIVE` base rate |
| --- | --- | --- |
| `BRONZE` | 0.15 | 0.25 |
| `SILVER` | 0.20 | 0.30 |
| `GOLD` | 0.25 | 0.35 |
| `PLATINUM` | 0.30 | 0.40 |

If the asset's `content_category` is `EDITORIAL`, an editorial bonus of 0.05 is added to that base rate; a `COMMERCIAL` asset adds nothing. The resulting rate is then capped so that it never exceeds 0.45 — that is, the locked `royalty_rate_snapshot_pct` is the smaller of 0.45 and the sum of the matrix base rate and the editorial bonus. Because the snapshot is taken at the moment of sale, any later change to the contributor's exclusivity or royalty level leaves already-recorded downloads untouched; the persisted `royalty_amount_cents` is the authoritative earning and is never recomputed against the contributor's current level. Downloads may be read individually and listed and filtered by `asset_id` or `contributor_id`.

### 3.5. Clearing, Reversals, Adjustments, and Career Levels

A pending earning clears when a finance administrator settles it, advancing the download from `earning_status` `PENDING` to `AVAILABLE`. Settlement is permitted only when the download is still `PENDING` and the current logical clock has reached or passed the download's `available_at`; an attempt to settle before that instant is rejected with `ERR_NOT_YET_CLEARED`, and an attempt to settle a download that is not `PENDING` yields `ERR_INVALID_STATE`. On settlement the contributor's `lifetime_earnings_cents` and `available_balance_cents` each increase by the download's `royalty_amount_cents`, the contributor's `royalty_level` is recomputed (see below), and both the download's `version` and the contributor's `version` increment by 1.

A download may be reversed as a chargeback, moving it to `REVERSED`. Reversing a `PENDING` download makes no balance change, because nothing was ever credited; only the download's `version` increments by 1. Reversing an `AVAILABLE` download is the compensating action for its settlement credit: the contributor's `lifetime_earnings_cents` and `available_balance_cents` each decrease by that download's `royalty_amount_cents`, the `royalty_level` is recomputed, and both the download's `version` and the contributor's `version` increment by 1. A reversal request carries a `reason`. Reversing an already-`REVERSED` download is rejected with `ERR_INVALID_STATE`. Because a settled download's earnings may already have been paid out, a post-clearing reversal can drive `available_balance_cents` temporarily negative — this clawback is the only way the available balance may fall below zero.

A finance administrator may also post an **earning adjustment**, a positive credit (a bonus or correction) carrying an `amount_cents` of at least 1 and a non-empty `reason`. The adjustment increases both `lifetime_earnings_cents` and `available_balance_cents` by `amount_cents`, recomputes `royalty_level`, and increments the contributor's `version` by 1. Unlike download earnings, adjustment amounts are never subject to payout withholding, though they do form part of the payout gross (see §3.7). Adjustments may be listed per contributor.

The contributor's `royalty_level` is a career tier derived solely from `lifetime_earnings_cents` and recomputed on every change to it (settlement, reversal, or adjustment). A lifetime total below 25,000 cents ($250.00) is `BRONZE`. From 25,000 cents up to but not including 100,000 cents ($1,000.00) is `SILVER` — a lifetime of exactly 25,000 cents is `SILVER`, while 24,999 cents is still `BRONZE`, because the lower bound is inclusive. From 100,000 cents up to but not including 500,000 cents ($5,000.00) is `GOLD`. A lifetime of 500,000 cents or more is `PLATINUM`.

### 3.6. Exclusivity Windows

A contributor may declare periods of exclusivity that lift its royalty rates into the higher column of the matrix in §3.4. An exclusivity window is created with a `start_at` (the inclusive start) and an `end_at` (the exclusive end), which must be strictly after `start_at`; a window whose `end_at` is at or before its `start_at` is rejected with `ERR_VALIDATION`. Each window is a half-open interval covering instants from `start_at` up to but not including `end_at`. A window is created in `status` `ACTIVE`, and creation increments the contributor's `version` by 1. Only `ACTIVE` windows carry weight; a `CANCELLED` window neither counts toward overlap nor confers exclusivity.

A new window must not overlap any existing `ACTIVE` window of the same contributor. Because the intervals are half-open, two windows that merely touch at an endpoint — one ending exactly where the next begins — do not overlap and are both allowed; any genuine interior overlap is rejected with `ERR_EXCLUSIVITY_OVERLAP`. A contributor's `exclusivity` field is read as a snapshot: it is `EXCLUSIVE` when some `ACTIVE` window covers the current logical clock (the clock is at or after that window's `start_at` and strictly before its `end_at`) and `NON_EXCLUSIVE` otherwise. This snapshot is exactly what the royalty-rate calculation reads at download time. Windows may be listed per contributor.

### 3.7. Payouts, Tax Withholding, and Disbursement

A contributor withdraws earnings by requesting a payout of its full available balance. The request carries `expected_contributor_version` and is subject, in order, to the ownership check, the stale-version check of §2.6 (`ERR_STALE_CONTRIBUTOR_VERSION`), the suspension gate (a `SUSPENDED` contributor is rejected with `ERR_CONTRIBUTOR_SUSPENDED`), and the fiscal minimum. The payout's gross is a snapshot of the contributor's `available_balance_cents` at request time; that gross must be at least the payout threshold of 10,000 cents ($100.00), and a request whose available balance falls short is rejected with `ERR_BELOW_PAYOUT_THRESHOLD`.

When the request is accepted, the new `Payout` is created in `status` `REQUESTED` with three computed amounts. `gross_amount_cents` is the snapshot of `available_balance_cents`. `withholding_cents` is the tax withheld over the contributor's currently `AVAILABLE` download earnings, computed as follows. The withholding rate depends on the contributor's most recently verified tax form (when more than one verified form exists, the one created most recently governs, and when the contributor has no verified form at all the rate is 0.00): a `W9` (domestic) filer withholds nothing, so the rate is 0.00 and the net equals the gross; a `W8BEN` (foreign) filer withholds at its `treaty_rate_pct` when one was supplied, or at the default foreign withholding rate of 0.30 when it was omitted. The rate is applied **per contributing line, rounded to a whole cent per line, and only then summed** — for each of the contributor's downloads whose `earning_status` is `AVAILABLE`, the platform multiplies that download's `royalty_amount_cents` by the withholding rate and rounds the product to the nearest cent using round half up, and `withholding_cents` is the sum of those per-line rounded amounts. This round-then-sum order is deliberate and differs from rounding a single grand total. Any earning-adjustment credits that form part of the gross are **not** withheld; withholding is drawn only from download earning lines. `net_amount_cents` is `gross_amount_cents` minus `withholding_cents` — equal to the gross for a domestic contributor and strictly less than the gross for any foreign contributor with a nonzero rate. Creating the payout debits `available_balance_cents` down to 0, locking the funds, and increments the contributor's `version` by 1.

A finance administrator advances the payout from `REQUESTED` to `PROCESSING`, then completes it. Because the balance was already debited at request time, completion only confirms disbursement: a normal completion moves the payout from `PROCESSING` to `PAID`. If the completion carries a `failed` flag indicating the disbursement failed, the payout instead moves from `PROCESSING` to `FAILED`, and the locked funds are restored — the contributor's `available_balance_cents` is increased back by the payout's `gross_amount_cents`, and both the payout's `version` and the contributor's `version` increment by 1. Advancing a payout from a state in which the requested transition is undefined (for instance processing a payout that is not `REQUESTED`, or completing one that is not `PROCESSING`) is rejected with `ERR_INVALID_STATE`. Payouts may be listed per contributor.

### 3.8. Takedowns, Legal Holds, Strikes, and Suspension

A compliance officer may file a takedown request against an asset, asserting an intellectual-property or legal claim. The filing carries a `claim_type` — one of `COPYRIGHT`, `TRADEMARK`, `PRIVACY`, or `MODEL_RELEASE` — and a non-empty `claimant_name` identifying the asserting party. On filing, the request is created in `status` `OPEN`, and the platform stamps a closed legal-hold interval on it: `hold_start` is set to the current logical clock, and `hold_end` is set to `hold_start` plus a hold period of 90 days. Both ends of this interval are inclusive.

Repeated filings against the same asset are rate-limited by a cooldown buffer. A new takedown on an asset must be filed at least 14 days after the end of the closed hold interval of any prior `UPHELD` takedown on that same asset — that is, the filing instant must be no earlier than that prior interval's `hold_end` plus 14 days. A filing that falls within the buffer is rejected with `ERR_TAKEDOWN_HOLD_CONFLICT`. Takedown requests may be listed and filtered by `asset_id`, and a single `TakedownRequest` may be read by its `id`; contributors and compliance officers may read them.

A compliance officer resolves an open takedown with a `decision` of `UPHOLD` or `DISMISS`. Dismissing an `OPEN` request moves it to `DISMISSED`, storing the optional `resolution_note`, and increments the takedown's `version` by 1. Upholding an `OPEN` request — permitted only while the challenged asset is still `ACCEPTED` — stores the optional `resolution_note`, moves the takedown to `UPHELD`, and triggers the full takedown cascade against the asset and its contributor. If the asset is not `ACCEPTED`, the uphold is rejected with `ERR_INVALID_STATE`.

The cascade is the platform's most consequential chain of side effects. Upholding drives the asset from `ACCEPTED` to `TAKEN_DOWN` (a terminal state) and, in one atomic operation: decrements the owning contributor's `accepted_asset_count` by 1; reverses every download of that asset whose `earning_status` is `PENDING` or `AVAILABLE`, moving each to `REVERSED` — where a reversed `AVAILABLE` download debits the contributor's `lifetime_earnings_cents` and `available_balance_cents` by its `royalty_amount_cents` and triggers a `royalty_level` recomputation, while a reversed `PENDING` download changes no balance; increments the contributor's `strike_count` by 1; and, when that new `strike_count` reaches the suspension threshold of 3, advances the contributor from `onboarding_status` `ACTIVE` to `SUSPENDED`. The asset's `version`, the contributor's `version`, and the takedown's `version` all increment as part of this cascade.

A contributor's `strike_count` counts the `UPHELD` takedowns against its assets. Reaching 3 strikes suspends the contributor: a `SUSPENDED` contributor is blocked from submitting assets and from requesting payouts, each such attempt returning `ERR_CONTRIBUTOR_SUSPENDED`. Suspension would lift only if the strike count later fell back below 3, but no operation in this API lowers a contributor's strike count, so in practice `SUSPENDED` is a sticky terminal condition. A contributor reaches `ACTIVE` in the first place only through tax verification (§3.1); the `PENDING`, `ACTIVE`, and `SUSPENDED` states are the whole of the contributor lifecycle.

## 4. Endpoint Definitions

Endpoints that create a new resource return HTTP 201; endpoints that read a resource or modify an existing one (including state transitions and the clock control) return HTTP 200. The request and response bodies for each endpoint are defined by the narratives in §3; the table below is a routing and authorization summary only.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/contributors` | Self-register a contributor (created in `PENDING`); no authentication required | `Contributor` |
| GET | `/contributors/{id}` | Read a contributor | `Contributor`, `Reviewer`, `ComplianceOfficer`, `FinanceAdmin` |
| GET | `/contributors` | List contributors (paginated) | `Contributor`, `Reviewer`, `ComplianceOfficer`, `FinanceAdmin` |
| POST | `/contributors/{id}/tax-forms` | Submit a tax form | `Contributor` |
| GET | `/contributors/{id}/tax-forms` | List a contributor's tax forms | `Contributor`, `ComplianceOfficer`, `FinanceAdmin` |
| POST | `/tax-forms/{id}/decision` | Verify or reject a submitted tax form | `ComplianceOfficer` |
| POST | `/contributors/{id}/model-releases` | Submit a model/property release | `Contributor` |
| GET | `/contributors/{id}/model-releases` | List a contributor's model releases | `Contributor`, `ComplianceOfficer` |
| POST | `/model-releases/{id}/decision` | Verify or reject a pending release | `ComplianceOfficer` |
| POST | `/contributors/{id}/exclusivity-windows` | Open an exclusivity window | `Contributor` |
| GET | `/contributors/{id}/exclusivity-windows` | List a contributor's exclusivity windows | `Contributor`, `ComplianceOfficer`, `FinanceAdmin` |
| POST | `/contributors/{id}/earning-adjustments` | Post a positive earnings credit | `FinanceAdmin` |
| GET | `/contributors/{id}/earning-adjustments` | List a contributor's earning adjustments | `Contributor`, `FinanceAdmin` |
| POST | `/contributors/{id}/payouts` | Request a payout of the full available balance | `Contributor` |
| GET | `/contributors/{id}/payouts` | List a contributor's payouts | `Contributor`, `FinanceAdmin` |
| POST | `/assets` | Create an asset in `DRAFT` | `Contributor` |
| GET | `/assets/{id}` | Read an asset | `Contributor`, `Reviewer`, `ComplianceOfficer`, `FinanceAdmin` |
| GET | `/assets` | List/filter assets | `Contributor`, `Reviewer`, `ComplianceOfficer`, `FinanceAdmin` |
| PATCH | `/assets/{id}` | Edit metadata while `DRAFT` or `REJECTED` | `Contributor` |
| POST | `/assets/{id}/submit` | Submit or resubmit an asset for review | `Contributor` |
| POST | `/assets/{id}/claim` | Claim a submitted asset for review | `Reviewer` |
| POST | `/assets/{id}/reviews` | Record an accept/reject decision | `Reviewer` |
| GET | `/reviews` | List reviews filtered by asset | `Contributor`, `Reviewer`, `ComplianceOfficer` |
| GET | `/reviews/{id}` | Read a single asset review | `Contributor`, `Reviewer`, `ComplianceOfficer` |
| POST | `/license-tiers` | Create a license tier (unique code) | `FinanceAdmin` |
| GET | `/license-tiers` | List license tiers | `Contributor`, `Reviewer`, `ComplianceOfficer`, `FinanceAdmin` |
| POST | `/downloads` | Record a licensing sale against an accepted asset | `FinanceAdmin` |
| GET | `/downloads` | List downloads filtered by asset or contributor | `Contributor`, `FinanceAdmin` |
| GET | `/downloads/{id}` | Read a download/earning | `Contributor`, `FinanceAdmin` |
| POST | `/downloads/{id}/settle` | Settle a cleared pending earning | `FinanceAdmin` |
| POST | `/downloads/{id}/reverse` | Chargeback a pending or available earning | `FinanceAdmin` |
| POST | `/payouts/{id}/process` | Advance a payout to processing | `FinanceAdmin` |
| POST | `/payouts/{id}/complete` | Complete a payout, or fail it and restore funds | `FinanceAdmin` |
| POST | `/assets/{id}/takedowns` | File a takedown request against an asset | `ComplianceOfficer` |
| GET | `/takedowns` | List takedown requests filtered by asset | `Contributor`, `ComplianceOfficer` |
| GET | `/takedowns/{id}` | Read a single takedown request | `Contributor`, `ComplianceOfficer` |
| POST | `/takedowns/{id}/decision` | Uphold (cascade) or dismiss a takedown | `ComplianceOfficer` |
| POST | `/_clock/set_current_utc` | Set the server logical clock | `FinanceAdmin` |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_STALE_CONTRIBUTOR_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_CONTRIBUTOR_SUSPENDED` | 403 |
| `ERR_CONTRIBUTOR_NOT_ACTIVE` | 409 |
| `ERR_RELEASE_NOT_VERIFIED` | 422 |
| `ERR_EXCLUSIVITY_OVERLAP` | 409 |
| `ERR_TAKEDOWN_HOLD_CONFLICT` | 409 |
| `ERR_NOT_SIMILAR_ENOUGH` | 422 |
| `ERR_VALIDATION` | 422 |
| `ERR_BELOW_PAYOUT_THRESHOLD` | 422 |
| `ERR_NOT_YET_CLEARED` | 409 |
| `ERR_MISSING_REJECT_REASON` | 422 |
| `ERR_MISSING_SIMILAR_TARGET` | 422 |
| `ERR_RELEASE_REQUIRED` | 422 |
