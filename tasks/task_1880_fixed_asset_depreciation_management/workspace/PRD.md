# Fixed Asset Depreciation API — Product Requirements Document

## 1. Introduction

Corporate fixed-asset accounting lives or dies on the accuracy of two parallel ledgers. The general ledger must reflect book depreciation computed under the company's capitalization policy, while the tax ledger must track depreciation under statutory recovery schedules that frequently diverge — different methods, different lives, and elective first-year bonus expensing. When a machine is sold, scrapped, or moved between cost centers, the gain or loss reported internally is rarely the same figure reported to the tax authority, and both must be derivable from the same underlying asset record. Reconciling these two views by spreadsheet is the pain point this system eliminates.

This document specifies a Fixed Asset & Depreciation Management API that covers the full asset lifecycle: construction-in-progress cost accumulation under a capitalization policy, capitalization into a registered asset, placement in service, monthly depreciation posting across book and tax ledgers, impairment review and write-down, disposal with dual-basis gain/loss computation, physical inventory with tagging reconciliation, and the import of external property-tax and insurance schedules. The system enforces segregation of duties between preparers and approvers, optimistic concurrency control on the asset record, and a strict monthly posting epoch so that the ledger can never be rewritten retroactively.

Four operator roles interact with the system. A fixed-asset accountant prepares projects, assets, depreciation runs, disposals, and impairment reviews. A controller approves the consequential steps — capitalization, disposals, write-downs, inventory close-out. An inventory clerk performs physical counts and drives recount cycles. A tax analyst feeds external schedules into the asset register.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, identifying the role under which the operator acts. A request missing either header, or presenting a role outside the declared set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not permitted for the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403).

The declared roles are exactly four, spelled as follows:

- `AssetAccountant` — the fixed-asset preparer. Builds CIP projects and posts cost lines, registers purchased assets and component assets, places assets in service, creates and posts depreciation runs, requests and posts disposals, and opens impairment reviews.
- `Controller` — the accounting approver. Owns asset-class policy, capitalizes or cancels projects, approves or rejects disposal requests, confirms or dismisses impairment reviews, closes inventory runs, and applies external schedules.
- `InventoryClerk` — performs physical inventory. Creates inventory runs, records count lines, and drives recount cycles.
- `TaxAnalyst` — imports property-tax and insurance schedule feeds for assets.

All four roles may call every read (GET) endpoint. Write endpoints are restricted as enumerated in §4.

For all four roles, `X-User-ID` is an **opaque operator identifier** not tied to any persisted entity. When `X-User-Role` is `AssetAccountant`, `Controller`, `InventoryClerk`, or `TaxAnalyst`, the server may record the identifier on resources the operator creates — for example as `created_by_user_id` on a `CapitalProject`, `requested_by_user_id` on a `Disposal`, or `approved_by_user_id` on an approved `Disposal` — but it is never compared to any entity's `id`. The recorded preparer identifiers matter only for segregation-of-duties comparisons (see §2.9).

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

All list endpoints accept the query parameters `limit` and `offset`. The `limit` parameter defaults to 10, must be at least 1, and may not exceed 100. The `offset` parameter defaults to 0. List responses include `limit`, `offset`, `total_count`, and `has_more` in the `meta` object, where `total_count` reports the full number of matching records and `has_more` indicates whether records remain beyond the returned window. Unless a list endpoint states otherwise, results are sorted by `created_at` in ascending order.

### 2.4. Common Resource Properties

Every persisted resource carries an `id` that is a server-minted UUID with no type prefix, assigned at creation. With one exception noted below, every resource also carries `created_at` and `updated_at` — ISO 8601 UTC timestamps with three fractional digits — and an integer `version` that starts at 1 on creation and increments by 1 on every mutation of that resource, including mutations caused by cascades from operations on other resources. `updated_at` is refreshed whenever the resource changes.

The exception is the `DepreciationEntry` ledger line. Depreciation entries are immutable once created: they carry only `id` and `created_at` and have **no** `updated_at` and **no** `version` field. No endpoint modifies or deletes a depreciation entry.

### 2.5. Monetary Representation, Precision and Rounding

All monetary amounts are represented as integer cents in fields whose names end in `_cents`. No floating-point money crosses the API. Where a calculation produces a fractional cent — monthly depreciation amounts, annual MACRS amounts divided by twelve, property tax computed from an assessed value — the result is rounded half-up to the nearest whole cent (zero decimal places). Rounding is applied **per posting period independently**: each month's depreciation is computed and rounded on its own, and the final month of a schedule takes the remaining un-depreciated balance as a remainder plug. A sum-then-round approach across multiple months is not permitted, because the per-month rounding decisions are pinned by this document.

### 2.6. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control against the `version` of a `FixedAsset`:

1. **Editing an asset.** A request to modify an asset's attributes must carry `expected_asset_version`, a non-optional input field equal to the asset's `version` as last observed by the client. Because every mutation of the asset — including cascaded mutations such as depreciation postings and impairment write-downs — increments `FixedAsset.version`, a client holding an older version is writing against a stale basis. If `expected_asset_version` does not match the asset's current `version`, the edit is rejected with `ERR_STALE_VERSION` (HTTP 412).
2. **Confirming an impairment review.** The confirm request must carry `expected_asset_version` equal to the `version` of the reviewed asset at the time the recoverable-value estimate was computed. If the asset's version has advanced since that observation — for example because a depreciation run has posted additional accumulated depreciation and changed the net book value — the confirm is rejected with `ERR_STALE_VERSION` (HTTP 412), because the write-down would be based on a stale carrying amount.

Endpoints not listed above do not take a version field. A successful guarded write increments the asset's `version` by 1, so the client must re-read before issuing its next guarded write.

### 2.7. Posting Periods and the Depreciation Epoch

Depreciation is posted in monthly periods identified by a `period` string in `YYYY-MM` format. The collection of posted periods forms a strictly forward-moving epoch. The first depreciation run ever created may target any period. Thereafter, a newly created run's `period` must be exactly one calendar month after the latest `POSTED` run's period; any other gap or overlap is rejected with `ERR_PERIOD_GAP` (HTTP 409). At most one run in status `OPEN` or `POSTED` may exist for a given period: creating a second run for a period that already has an `OPEN` run is rejected with `ERR_DUPLICATE_RUN_PERIOD` (HTTP 409), and for a period that already has a `POSTED` run with `ERR_PERIOD_ALREADY_POSTED` (HTTP 409).

A disposal's `effective_date` determines its effective period (the `YYYY-MM` of that date). The effective period must be **later than** the latest `POSTED` run period; this rule is checked when the disposal is requested and re-validated when the disposal is posted. A disposal whose effective period is on or before the latest posted period is rejected with `ERR_PERIOD_CLOSED` (HTTP 409).

### 2.8. Dual-Ledger Accounting

Every depreciable asset is carried simultaneously on two ledgers, identified by the `ledger` value `BOOK` or `TAX`. The two ledgers share the same acquisition cost but diverge in method, life, and elective expensing: the book ledger follows the asset's `book_method` over its `useful_life_months` net of salvage value and impairment, while the tax ledger follows the asset's `tax_method` using statutory rate tables and, when elected and permitted, first-year bonus depreciation. Accumulated depreciation is tracked separately per ledger as `accumulated_book_cents` and `accumulated_tax_cents`, and each ledger's entries are distinguishable by `ledger` on every `DepreciationEntry`.

Two consequences follow. First, an asset may be fully depreciated on one ledger while still depreciating on the other; each ledger's eligibility is evaluated independently at every posting. Second, the asset lifecycle is driven by the book ledger only — the tax ledger never triggers the automatic transition to `FULLY_DEPRECIATED`, and gain/loss at disposal is computed twice, once per basis, because impairment write-downs reduce the book basis but never the tax basis.

### 2.9. Segregation of Duties

Three consequential approvals are segregation-of-duties (SoD) protected: the operator who prepared a record may not be the one who approves it. Specifically:

- **Capitalization** — the `Controller` capitalizing a project must present an `X-User-ID` different from the project's recorded `created_by_user_id`.
- **Disposal approval** — the `Controller` approving a disposal must present an `X-User-ID` different from the disposal's recorded `requested_by_user_id`.
- **Impairment confirm** — for a review whose `source` is `MANUAL`, the confirming `Controller`'s `X-User-ID` must differ from the review's `created_by_user_id`. Reviews whose `source` is `INVENTORY` are created by the system itself (their `created_by_user_id` is the literal string `system`), so the SoD check is skipped for them and any `Controller` may confirm.

A violation of any of these three rules is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).

### 2.10. Validation Order

When multiple validation rules could reject the same request, the server evaluates them in a fixed priority order so the returned error is deterministic. The order is: **(1) authentication** — presence and validity of `X-User-ID` and `X-User-Role` (`ERR_UNAUTHENTICATED`); **(2) authorization and segregation of duties** — role permission for the endpoint (`ERR_FORBIDDEN`) and the SoD comparisons (`ERR_SEGREGATION_OF_DUTIES`); **(3) existence** — every path id and every body foreign-key reference must resolve (`ERR_NOT_FOUND`, or `ERR_ASSET_NOT_IN_SCOPE` for a count line whose asset was not seeded into the run); **(4) state** — the target entity must be in the required from-state (`ERR_INVALID_STATE`, `ERR_PROJECT_NOT_OPEN`, `ERR_ASSET_NOT_IN_SERVICE`, `ERR_ALREADY_DISPOSED`, `ERR_RUN_NOT_COUNTING`); **(5) compliance gate** — the open-inventory-exception gate on disposal posting (`ERR_ASSET_UNDER_INVENTORY_REVIEW`); **(6) uniqueness and structural rules** (`ERR_DUPLICATE_TAG`, `ERR_DUPLICATE_RUN_PERIOD`, `ERR_PERIOD_ALREADY_POSTED`, `ERR_IMPAIRMENT_REVIEW_OPEN`, `ERR_DUPLICATE_SCHEDULE`, `ERR_FIELD_IMMUTABLE`); **(7) temporal period rules** (`ERR_PERIOD_GAP`, `ERR_PERIOD_CLOSED`); and **(8) monetary and field-value rules** (`ERR_BELOW_CAPITALIZATION_THRESHOLD`, `ERR_INVALID_AMOUNT`, `ERR_INVALID_SALVAGE_VALUE`, `ERR_INVALID_DISPOSAL_FIELDS`, `ERR_BONUS_NOT_ALLOWED`, `ERR_NO_IMPAIRMENT_INDICATED`, `ERR_INVALID_SCHEDULE_FIELDS`). A malformed payload — a missing required field, an unknown enum value, or a wrongly typed value — is rejected with `ERR_INVALID_REQUEST` (HTTP 400) before any business rule is evaluated.

## 3. Business Logic & Workflows

### 3.1. Capitalization Policy and Construction-in-Progress

Everything begins with policy. A `Controller` defines an **asset class** — the capitalization policy for a family of assets — by supplying a unique `class_code`, a display `name`, the `capitalization_threshold_cents` below which no cost may be capitalized, a `default_useful_life_months` greater than zero, the default `book_method` (either `STRAIGHT_LINE` or `DOUBLE_DECLINING`), the default `tax_method` (one of `MACRS_5YR`, `MACRS_7YR`, or `TAX_STRAIGHT_LINE`), and a `bonus_depreciation_allowed` flag controlling whether assets of the class may elect first-year bonus depreciation. A duplicate `class_code` is rejected with `ERR_DUPLICATE_TAG`.

While an asset is being built or assembled, its costs accumulate on a **capital project**. An `AssetAccountant` opens a project with a unique `project_code` (duplicates likewise rejected with `ERR_DUPLICATE_TAG`), a `name`, and the `asset_class_id` of the class the eventual asset will belong to. The project is born in status `OPEN`, its `total_accumulated_cents` starts at zero, and the creator's `X-User-ID` is recorded as `created_by_user_id` — the value that will later block self-capitalization. Projects can be listed and filtered by `asset_class_id`, by `capitalized_asset_id`, or by `status`.

Costs flow onto the project as **CIP cost lines**. An `AssetAccountant` posts a line by naming the `project_id`, an `amount_cents` strictly greater than zero (anything else is `ERR_INVALID_AMOUNT`), a `cost_type` of `MATERIAL`, `LABOR`, `VENDOR_INVOICE`, or `OTHER`, and the `incurred_date` on which the cost was incurred. A line is born in status `POSTED` and immediately counts toward the project's total. The project's `total_accumulated_cents` is, at all times, exactly the sum of `amount_cents` over that project's lines in status `POSTED`; reversed lines are excluded. If a line was posted in error, an `AssetAccountant` reverses it: the line moves from `POSTED` to the terminal status `REVERSED`, the project's `total_accumulated_cents` is recomputed (decreasing by the line's `amount_cents`), and the project's `version` increments with `updated_at` refreshed. Both posting and reversing a line require the parent project to still be `OPEN`; against a `CAPITALIZED` or `CANCELLED` project the attempt is rejected with `ERR_PROJECT_NOT_OPEN`, and reversing a line that is not `POSTED` is rejected with `ERR_INVALID_STATE`.

Capitalization converts the accumulated cost into an asset. A `Controller` capitalizes an `OPEN` project, supplying the `asset_tag` and `description` for the new asset in the payload. Three checks guard this transition, evaluated under the §2.10 ordering: the project must be `OPEN` (else `ERR_PROJECT_NOT_OPEN`); the controller must not be the project's creator, by SoD (else `ERR_SEGREGATION_OF_DUTIES`); and the project's `total_accumulated_cents` must be at least the `capitalization_threshold_cents` of the project's asset class (else `ERR_BELOW_CAPITALIZATION_THRESHOLD`). On success the project transitions from `OPEN` to `CAPITALIZED`, its `capitalized_asset_id` is set to the new asset, and a `FixedAsset` is created in status `DRAFT` with `source` equal to `CIP_CAPITALIZATION`, the project's `asset_class_id`, and an `acquisition_cost_cents` equal to the project's accumulated total. The new asset's remaining policy fields default from its class, exactly as for a directly purchased asset (§3.2). Alternatively, a `Controller` may cancel an `OPEN` project: the project moves from `OPEN` to `CANCELLED`, no asset is created, and its posted cost lines remain `POSTED` as an audit trail — the project is simply written off.

### 3.2. Asset Registration, Components, and Placement in Service

A directly purchased asset is registered by an `AssetAccountant` with a unique `asset_tag` (duplicates rejected with `ERR_DUPLICATE_TAG`), a free-text `description`, the `asset_class_id`, an `acquisition_cost_cents` strictly greater than zero, the owning `cost_center`, and a `location` code. Four policy fields may be overridden at registration or left to default from the class: `salvage_value_cents` (default zero; it must be at least zero and strictly less than `acquisition_cost_cents`, else `ERR_INVALID_SALVAGE_VALUE`), `useful_life_months` (defaulting from the class's `default_useful_life_months`), `book_method`, and `tax_method`. The `bonus_elected` flag defaults to false; setting it to true elects first-year bonus depreciation and is permitted only when the class's `bonus_depreciation_allowed` is true — otherwise the registration is rejected with `ERR_BONUS_NOT_ALLOWED`. A directly registered asset is born in status `DRAFT` with `source` equal to `PURCHASE`.

**Component accounting** handles major repairs and betterments. When the registration payload includes a `parent_asset_id`, the new record is a component asset: its `source` becomes `COMPONENT_ADDITION`, and the parent asset must be `IN_SERVICE` at the time the component is created (a DRAFT or already-disposed parent makes the request invalid — a `DISPOSED` parent yields `ERR_ALREADY_DISPOSED`). A component is itself a full asset with its own tag, cost, life, and depreciation. Because a minor repair is an expense rather than an asset, a component whose `acquisition_cost_cents` is below its class's `capitalization_threshold_cents` is rejected with `ERR_BELOW_CAPITALIZATION_THRESHOLD` and must be expensed outside the system instead. Assets can be listed and filtered by `asset_class_id`, `parent_asset_id`, `status`, `location`, or `cost_center`, which is also how the components of a primary asset are enumerated.

An asset's monetary position is carried in four derived figures. `accumulated_book_cents` is the sum of `amount_cents` over the asset's `BOOK` depreciation entries; `accumulated_tax_cents` is the same over its `TAX` entries; `impairment_total_cents` is the sum of `write_down_cents` over the asset's `WRITTEN_DOWN` impairment reviews; and `net_book_value_cents` is the acquisition cost minus `accumulated_book_cents` minus `impairment_total_cents`. All four start at zero (the first three) or at acquisition cost (the last) on a fresh asset.

While an asset is `DRAFT`, an `AssetAccountant` may edit any writable attribute — `description`, `acquisition_cost_cents`, `salvage_value_cents`, `useful_life_months`, `book_method`, `tax_method`, `bonus_elected`, `location`, and `cost_center` — through the OCC-guarded edit endpoint (§2.6). Once the asset is `IN_SERVICE`, the edit surface narrows to the prospective, non-historical fields: only `useful_life_months`, `salvage_value_cents`, `location`, `cost_center`, and `description` may be touched. An edit to an in-service asset naming any other field is rejected with `ERR_FIELD_IMMUTABLE` (HTTP 422). Every successful edit increments the asset's `version`.

Nothing depreciates until it is placed in service. An `AssetAccountant` places a `DRAFT` asset in service by supplying the `in_service_date`; the asset transitions from `DRAFT` to `IN_SERVICE` and the date is recorded. Placing an asset that is not `DRAFT` in service is rejected with `ERR_INVALID_STATE`. The in-service date fixes two things downstream: the period of the date (its `YYYY-MM`) is the first period in which the asset is eligible for depreciation, and the year of the date is tax year 1 for MACRS purposes. The disposal workflow later requires that a disposal's `effective_date` never precedes the asset's `in_service_date` (§3.5).

### 3.3. Monthly Depreciation Posting

Depreciation is posted by an `AssetAccountant` through a **depreciation run** — a checkpoint that advances the posting epoch described in §2.7. Creating a run requires only the target `period`; the run is born `OPEN`, and the period-sequence and uniqueness rules of §2.7 apply at creation. A single run per period exists in status `OPEN` or `POSTED`.

Posting the run sweeps every eligible asset. Eligibility is evaluated per asset and per ledger: the asset must be `IN_SERVICE` (assets in `DRAFT`, `FULLY_DEPRECIATED`, or `DISPOSED` are excluded), and its in-service period must be on or before the run's `period`. Within that set, the **book** entry is created only while the asset still has book eligibility — the count of its existing `BOOK` entries is less than `useful_life_months` and its `accumulated_book_cents` is below the depreciable basis — and the **tax** entry is created only while the asset still has tax eligibility. An asset exhausted on one ledger continues to receive entries on the other.

The **book amount** for a period depends on the asset's `book_method`, computed over the depreciable basis, defined as `acquisition_cost_cents` minus `salvage_value_cents` minus `impairment_total_cents`:

- Under `STRAIGHT_LINE`, the amount is the remaining basis (depreciable basis minus `accumulated_book_cents`) divided evenly across the remaining months (`useful_life_months` minus the number of book entries already posted), rounded half-up to a whole cent. After an impairment write-down the reduced basis simply spreads over the remaining months, so the charge level drops prospectively.
- Under `DOUBLE_DECLINING`, the amount is the current `net_book_value_cents` multiplied by two and divided by `useful_life_months`, rounded half-up to a whole cent — an accelerated charge on a declining balance. If adding that amount would push `accumulated_book_cents` past the depreciable basis, the amount is capped at exactly the remaining basis, so the ledger never over-depreciates.
- In the **final month** of the schedule under either method — when the number of book entries already posted equals `useful_life_months` minus one — the amount is the remainder plug: the depreciable basis minus `accumulated_book_cents`, whatever that residue is after prior months' rounding.

The **tax amount** follows the asset's `tax_method`. The tax year index of a run period is the run period's calendar year minus the in-service year plus one; tax years are calendar years, year 1 begins at the in-service year, and all twelve monthly entries of year 1 are posted regardless of the in-service month, because the first-year convention is already baked into the year-1 rate.

- Under `TAX_STRAIGHT_LINE`, each period's amount is `acquisition_cost_cents` divided by `useful_life_months`, rounded half-up to a whole cent, and the final tax month takes the plug of `acquisition_cost_cents` minus `accumulated_tax_cents` so the tax ledger lands exactly on cost.
- Under `MACRS_5YR` or `MACRS_7YR`, an annual amount is computed from a statutory rate table and then spread across the calendar year. The five-year table's annual rates, for tax years 1 through 6, are 20.00%, 32.00%, 19.20%, 11.52%, 11.52%, and 5.76%. The seven-year table's rates, for tax years 1 through 8, are 14.29%, 24.49%, 17.49%, 12.49%, 8.93%, 8.92%, 8.93%, and 4.46%. If the tax year index exceeds the table's length, the tax basis is exhausted and no tax entry is created. The annual amount is the applicable rate multiplied by the bonus-adjusted base (below), rounded half-up to a whole cent; each monthly entry within the tax year is one twelfth of that annual amount, rounded half-up to a whole cent, **except** the December entry, which takes the annual amount minus the sum of the prior eleven monthly amounts so the year reconciles exactly.
- **Bonus depreciation.** When `bonus_elected` is true, the year-1 annual amount is sixty percent of `acquisition_cost_cents` expensed immediately, plus the applicable year-1 table rate applied to the remaining forty percent. In years 2 and beyond, the base for the rate table is the remaining forty percent of `acquisition_cost_cents`. When bonus is not elected (or the class disallows it), the base is the full `acquisition_cost_cents` in every year.

Regardless of method, `accumulated_tax_cents` never exceeds `acquisition_cost_cents`: an entry that would cross that cap is reduced to exactly `acquisition_cost_cents` minus the current `accumulated_tax_cents`.

Posting is atomic and cascading. Every entry created is a `DepreciationEntry` with `source` equal to `RUN`, the run's id recorded as its `run_id`, the `asset_id`, the `ledger`, the `period`, and the `amount_cents`; its `disposal_id` is null. Each created entry adds its `amount_cents` to the asset's `accumulated_book_cents` or `accumulated_tax_cents` (never negative amounts) and increments the asset's `version`. After an asset's entries are applied, if its `accumulated_book_cents` has reached the depreciable basis — acquisition cost minus salvage minus impairment — the asset automatically transitions from `IN_SERVICE` to `FULLY_DEPRECIATED`; the tax ledger never triggers this transition. The run itself records the sweep's summary: `entries_created_count`, `total_book_amount_cents` (the sum of `BOOK` entry amounts in the run), and `total_tax_amount_cents` (the sum of `TAX` amounts). The run's status moves from `OPEN` to `POSTED`, which is terminal; posting a run that is not `OPEN` is rejected with `ERR_INVALID_STATE`. Depreciation entries can be listed and filtered by `run_id`, `asset_id`, `disposal_id`, `ledger`, or `period`.

### 3.4. Impairment Review and Write-Down

When events suggest an asset's carrying amount may not be recoverable, an `AssetAccountant` opens an **impairment review** against an `IN_SERVICE` asset, naming the `asset_id` and an `indicator` of `DAMAGE`, `OBSOLESCENCE`, or `MARKET_DECLINE`. Opening a review against a `DRAFT` asset is rejected with `ERR_ASSET_NOT_IN_SERVICE`; against a `DISPOSED` asset with `ERR_ALREADY_DISPOSED`. At most one review per asset may be `OPEN` at a time — a second open attempt is rejected with `ERR_IMPAIRMENT_REVIEW_OPEN`. A manually opened review records the opener's `X-User-ID` as `created_by_user_id` and its `source` as `MANUAL`. Reviews can be listed and filtered by `asset_id` or `status`.

A `Controller` then either dismisses or confirms the review. Dismissing moves the review from `OPEN` to the terminal status `DISMISSED` with no financial effect; it is the correct outcome when the carrying amount is fully recoverable. Confirming the review carries the `recoverable_value_cents` — the estimated recoverable amount, zero or greater — together with the OCC token `expected_asset_version` (§2.6). The write-down is computed as `net_book_value_cents` minus `recoverable_value_cents`; if that difference is zero or negative, there is nothing to write down, the confirm is rejected with `ERR_NO_IMPAIRMENT_INDICATED` (HTTP 422), and the review should be dismissed instead. For a `MANUAL` review the confirming controller must not be the opener (SoD, §2.9); for an `INVENTORY`-sourced review that check is skipped.

A successful confirm writes `write_down_cents` onto the review, moves it from `OPEN` to the terminal status `WRITTEN_DOWN`, and cascades onto the asset in one atomic step: the asset's `impairment_total_cents` increases by `write_down_cents`, its `net_book_value_cents` is recomputed, its `version` increments by one, and its remaining depreciable basis — acquisition cost minus `salvage_value_cents` minus `accumulated_book_cents` minus the new `impairment_total_cents` — is re-evaluated. If the remaining basis is zero or negative, the asset automatically transitions from `IN_SERVICE` to `FULLY_DEPRECIATED`. Future book depreciation then spreads the reduced basis over the remaining months, as described in §3.3. Confirming or dismissing a review that is no longer `OPEN` is rejected with `ERR_INVALID_STATE`.

### 3.5. Disposal, Transfer, and Gain/Loss

Disposal begins with a request. An `AssetAccountant` requests a disposal by naming the `asset_id`, a `disposal_type` of `SALE`, `SCRAP`, or `TRANSFER`, and the `effective_date`. The asset must be `IN_SERVICE` or `FULLY_DEPRECIATED`: a `DRAFT` asset yields `ERR_ASSET_NOT_IN_SERVICE` and a `DISPOSED` asset yields `ERR_ALREADY_DISPOSED`. The field rules depend on the type. A `SALE` requires an explicit `proceeds_cents` of zero or more. A `SCRAP` accepts an optional `proceeds_cents` (default zero) — salvage occasionally has scrap value. A `TRANSFER` is an inter-cost-center move: it requires `transfer_to_cost_center`, forbids it for the other two types, and demands `proceeds_cents` equal to zero. A negative `proceeds_cents` is `ERR_INVALID_AMOUNT`; the type-specific field combinations, as well as an `effective_date` earlier than the asset's `in_service_date`, are rejected with `ERR_INVALID_DISPOSAL_FIELDS` (HTTP 422). The effective-period rule of §2.7 is checked at request time (`ERR_PERIOD_CLOSED`). A new request is born in status `REQUESTED` with the requester's `X-User-ID` recorded as `requested_by_user_id`. Disposals can be listed and filtered by `asset_id` or `status`.

A `Controller` then dispositions the request. Approval moves the disposal from `REQUESTED` to `APPROVED` and records the approver's `X-User-ID` as `approved_by_user_id`; the approver must differ from `requested_by_user_id` (SoD — `ERR_SEGREGATION_OF_DUTIES`). Rejection moves it from `REQUESTED` to `REJECTED`, optionally carrying a free-text `reason`. A rejected request is not the end: the `AssetAccountant` may resubmit it with corrected `proceeds_cents`, `effective_date`, or `transfer_to_cost_center` values, which replace the prior values and are re-validated against the same field rules; the disposal returns from `REJECTED` to `REQUESTED`, provided the asset is still `IN_SERVICE` or `FULLY_DEPRECIATED` (else `ERR_ALREADY_DISPOSED`). Acting on a disposal that is not in the required from-state is `ERR_INVALID_STATE`.

Posting is where the ledger moves, and it is restricted to `APPROVED` disposals (`ERR_INVALID_STATE` otherwise). Two gates are re-validated at post time. First, the effective period must still be later than the latest `POSTED` run period (`ERR_PERIOD_CLOSED`). Second, the **compliance gate**: for `SALE` and `TRANSFER`, the asset's `open_inventory_exception` flag must be false — an asset with an unresolved inventory exception may not leave the books or change hands, and the post is rejected with `ERR_ASSET_UNDER_INVENTORY_REVIEW` (HTTP 409). `SCRAP` is exempt from this gate because scrapping is precisely the resolution path for an asset that has gone missing.

For `SALE` and `SCRAP`, posting derecognizes the asset in a pinned evaluation order. **Step one — final-period depreciation:** if the asset is `IN_SERVICE` and the day-of-month of the `effective_date` is 15 or later, the effective period's `BOOK` and `TAX` entries are created with `source` equal to `DISPOSAL_FINAL`, the disposal's id recorded as their `disposal_id` (and `run_id` null), computed exactly per the §3.3 methods and applied to `accumulated_book_cents` and `accumulated_tax_cents`. If the day-of-month is before the 15th, no final entries are created — the mid-month convention treats the asset as disposed before the period's depreciation accrues. **Step two — book gain/loss:** `book_gain_loss_cents` is `proceeds_cents` minus the net book carrying amount, that is, minus (`acquisition_cost_cents` − `accumulated_book_cents` − `impairment_total_cents`). **Step three — tax gain/loss:** `tax_gain_loss_cents` is `proceeds_cents` minus the tax basis (`acquisition_cost_cents` − `accumulated_tax_cents`); impairment is ignored on the tax side, so the same disposal routinely produces two different gain/loss figures. The asset then transitions from `IN_SERVICE` or `FULLY_DEPRECIATED` to the terminal status `DISPOSED`.

Disposal cascades through components. When a primary asset is disposed by sale or scrap, every child asset whose `parent_asset_id` points at it and whose status is `IN_SERVICE` or `FULLY_DEPRECIATED` is itself disposed automatically: the system spawns a companion `SCRAP` disposal with zero proceeds, `auto_created` set to true, and immediate posting, each component computing its own final entries and its own book and tax gain/loss exactly as above. A component already `DRAFT` or `DISPOSED` is untouched.

A `TRANSFER` posting is deliberately quieter: the asset's `cost_center` is set to the disposal's `transfer_to_cost_center`, both gain/loss fields are set to zero, no final entries are created, the asset remains `IN_SERVICE` (a self-transition that records the move), and components are **not** cascaded — a transfer moves the primary asset's cost center only.

### 3.6. Physical Inventory and Tagging Reconciliation

Periodic physical verification is organized as an **inventory run**, created by an `InventoryClerk` with a display `name`, a `scope_type` of `ALL`, `LOCATION`, or `COST_CENTER`, and — required whenever the scope is `LOCATION` or `COST_CENTER` — a `scope_value` that is matched against assets' `location` or `cost_center` respectively. Creation seeds one count line per in-scope asset whose status is `IN_SERVICE` or `FULLY_DEPRECIATED`; each seeded line records the run's id as `run_id` and the asset's id as `asset_id`, starts with `found` null and `reconciliation_status` equal to `PENDING`, and the run's `expected_count` is set to the number of seeded lines. The run is born in status `COUNTING`.

The clerk then walks the floor and records counts. Recording a count is an **upsert** against a seeded line: the payload names the `asset_id`, whether the asset was physically `found`, the `counted_location` where it was seen (required when `found` is true), and a `condition` of `GOOD` or `DAMAGED` (default `GOOD`). The upsert is valid only while the run is `COUNTING` — against a `RECONCILING` or `CLOSED` run it is rejected with `ERR_RUN_NOT_COUNTING` — and only for an asset that was actually seeded into the run, else `ERR_ASSET_NOT_IN_SCOPE`. Each upsert recomputes the line's `reconciliation_status`: still `PENDING` while `found` is null; `MISSING` when `found` is false; `MATCHED` when the asset was found and `counted_location` equals the asset's `location`; and `LOCATION_MISMATCH` when it was found somewhere else. The same derivation is re-evaluated when a run closes and whenever an asset's `location` is edited, so a legitimate location correction can turn a mismatch into a match without re-counting. The run's counters recount the lines by status: `matched_count` for `MATCHED` lines, `mismatch_count` for `LOCATION_MISMATCH` lines, and `missing_count` for `MISSING` lines **excluding** any whose asset has since become `DISPOSED`. An asset's `open_inventory_exception` flag is true exactly when some line for that asset is `MISSING` or `LOCATION_MISMATCH` in a run that is not yet `CLOSED` — the flag that the §3.5 compliance gate consults.

A `DAMAGED` count on a found asset has a second effect: it automatically opens an impairment review with `indicator` equal to `DAMAGE` and `source` equal to `INVENTORY`, created by the system itself with `created_by_user_id` set to the literal `system` — unless a review is already `OPEN` for that asset, in which case no duplicate is created. Physical damage thereby flows into the §3.4 write-down workflow without manual triage.

Reconciliation proceeds in cycles. When every seeded line has been counted — `found` is non-null on all of them — the clerk begins reconciliation, moving the run from `COUNTING` to `RECONCILING`; attempting it with any line still uncounted is rejected with `ERR_UNCOUNTED_LINES`. If discrepancies surface, the clerk sends the run back from `RECONCILING` to `COUNTING` for a recount, after which lines may be re-counted (upserted) again. Finally, a `Controller` closes a `RECONCILING` run — permitted only when every seeded line is `MATCHED` **or** its asset is `DISPOSED` (an asset scrapped as missing via the §3.5 exempt path therefore does not block the close) — otherwise the close is rejected with `ERR_UNRESOLVED_INVENTORY_ITEMS`. Closing is terminal (`CLOSED`) and clears `open_inventory_exception` on the counted assets, recomputed from the remaining non-closed runs. Any transition attempted from the wrong state is `ERR_INVALID_STATE`. Count history is available both per run and per asset across runs.

### 3.7. Property-Tax and Insurance Schedules

The asset register also feeds property-tax filings and insurance renewals. A `TaxAnalyst` imports an **external schedule** row for an asset, naming the `asset_id`, a `schedule_type` of `PROPERTY_TAX` or `INSURANCE`, and the `schedule_year` the row covers. Only one row may exist per combination of asset, schedule type, and year; a duplicate is rejected with `ERR_DUPLICATE_SCHEDULE`. The two types carry different payloads: a `PROPERTY_TAX` row requires `assessed_value_cents` and leaves `annual_premium_cents` null, while an `INSURANCE` row requires `annual_premium_cents` and leaves `assessed_value_cents` null; mixing these up is rejected with `ERR_INVALID_SCHEDULE_FIELDS` (HTTP 422).

For a `PROPERTY_TAX` row, the system derives the tax at import time: `property_tax_amount_cents` is the `assessed_value_cents` multiplied by the 1.25% mill rate, rounded half-up to a whole cent. For an `INSURANCE` row, `property_tax_amount_cents` is null. The row is born in status `IMPORTED`. A `Controller` subsequently applies the row, moving it from `IMPORTED` to the terminal status `APPLIED`; applying against a `DISPOSED` asset is rejected with `ERR_ALREADY_DISPOSED`, and applying a row not in `IMPORTED` is `ERR_INVALID_STATE`. An asset's schedule rows are listed from the asset's side.

## 4. Endpoint Definitions

All endpoints are served from the API root. Status code rules: creating a new resource returns 201; all other successful operations — reads, edits, and state-transition actions — return 200. Errors carry the envelope and codes of §2.2 and §5.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/asset-classes` | Create an asset class (capitalization policy) | Controller |
| GET | `/asset-classes/{id}` | Get an asset class | AssetAccountant, Controller, InventoryClerk, TaxAnalyst |
| POST | `/capital-projects` | Create a CIP project | AssetAccountant |
| GET | `/capital-projects` | List projects with filters | AssetAccountant, Controller, InventoryClerk, TaxAnalyst |
| GET | `/capital-projects/{id}` | Get a project | AssetAccountant, Controller, InventoryClerk, TaxAnalyst |
| POST | `/capital-projects/{id}/capitalize` | Capitalize an OPEN project into a new DRAFT asset (SoD: creator cannot capitalize) | Controller |
| POST | `/capital-projects/{id}/cancel` | Cancel (write off) an OPEN project | Controller |
| POST | `/cip-cost-lines` | Post a cost line to an OPEN project | AssetAccountant |
| GET | `/capital-projects/{id}/cost-lines` | List cost lines of a project | AssetAccountant, Controller, InventoryClerk, TaxAnalyst |
| POST | `/cip-cost-lines/{id}/reverse` | Reverse a POSTED cost line | AssetAccountant |
| POST | `/fixed-assets` | Create a purchased asset, or a component (major repair) when `parent_asset_id` is given | AssetAccountant |
| GET | `/fixed-assets` | List assets with filters | AssetAccountant, Controller, InventoryClerk, TaxAnalyst |
| GET | `/fixed-assets/{id}` | Get an asset | AssetAccountant, Controller, InventoryClerk, TaxAnalyst |
| PATCH | `/fixed-assets/{id}` | Edit asset attributes (OCC-guarded; DRAFT fully editable, IN_SERVICE prospective fields only) | AssetAccountant |
| POST | `/fixed-assets/{id}/place-in-service` | Place a DRAFT asset in service | AssetAccountant |
| POST | `/depreciation-runs` | Create a run for a period (exactly latest POSTED period + 1 month; any period if none posted) | AssetAccountant |
| GET | `/depreciation-runs/{id}` | Get a run | AssetAccountant, Controller, InventoryClerk, TaxAnalyst |
| POST | `/depreciation-runs/{id}/post` | Post the run: create entries for all eligible assets and advance the epoch | AssetAccountant |
| GET | `/depreciation-entries` | List depreciation entries with filters | AssetAccountant, Controller, InventoryClerk, TaxAnalyst |
| GET | `/depreciation-entries/{id}` | Get a depreciation entry | AssetAccountant, Controller, InventoryClerk, TaxAnalyst |
| POST | `/disposals` | Request a disposal (SALE/SCRAP derecognize; TRANSFER moves cost center) | AssetAccountant |
| GET | `/disposals` | List disposals with filters | AssetAccountant, Controller, InventoryClerk, TaxAnalyst |
| GET | `/disposals/{id}` | Get a disposal | AssetAccountant, Controller, InventoryClerk, TaxAnalyst |
| POST | `/disposals/{id}/approve` | Approve a REQUESTED disposal (SoD: approver differs from requester) | Controller |
| POST | `/disposals/{id}/reject` | Reject a REQUESTED disposal | Controller |
| POST | `/disposals/{id}/resubmit` | Resubmit a REJECTED disposal with corrected fields | AssetAccountant |
| POST | `/disposals/{id}/post` | Post an APPROVED disposal: final entries, gain/loss, derecognition or transfer | AssetAccountant |
| POST | `/inventory-runs` | Create an inventory run (starts COUNTING; seeds one PENDING line per in-scope IN_SERVICE/FULLY_DEPRECIATED asset) | InventoryClerk |
| GET | `/inventory-runs/{id}` | Get an inventory run | AssetAccountant, Controller, InventoryClerk, TaxAnalyst |
| POST | `/inventory-runs/{id}/count-lines` | Record (upsert) a physical count for an asset in the run | InventoryClerk |
| GET | `/inventory-runs/{id}/count-lines` | List count lines of a run | AssetAccountant, Controller, InventoryClerk, TaxAnalyst |
| GET | `/fixed-assets/{id}/count-lines` | Count history of an asset across runs | AssetAccountant, Controller, InventoryClerk, TaxAnalyst |
| POST | `/inventory-runs/{id}/begin-reconciliation` | Move COUNTING to RECONCILING (all seeded lines counted) | InventoryClerk |
| POST | `/inventory-runs/{id}/recount` | Move RECONCILING back to COUNTING (recount cycle) | InventoryClerk |
| POST | `/inventory-runs/{id}/close` | Close a RECONCILING run (every line MATCHED or its asset DISPOSED) | Controller |
| POST | `/impairment-reviews` | Open an impairment review on an IN_SERVICE asset (one OPEN per asset) | AssetAccountant |
| GET | `/impairment-reviews` | List impairment reviews with filters | AssetAccountant, Controller, InventoryClerk, TaxAnalyst |
| GET | `/impairment-reviews/{id}` | Get an impairment review | AssetAccountant, Controller, InventoryClerk, TaxAnalyst |
| POST | `/impairment-reviews/{id}/confirm` | Confirm write-down at a recoverable value (OCC pins asset version; SoD vs creator) | Controller |
| POST | `/impairment-reviews/{id}/dismiss` | Dismiss an OPEN review without write-down | Controller |
| POST | `/external-schedules` | Import a property-tax or insurance schedule row for an asset | TaxAnalyst |
| GET | `/fixed-assets/{id}/external-schedules` | List external schedules of an asset | AssetAccountant, Controller, InventoryClerk, TaxAnalyst |
| POST | `/external-schedules/{id}/apply` | Apply an IMPORTED schedule | Controller |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_PROJECT_NOT_OPEN` | 409 |
| `ERR_ASSET_NOT_IN_SERVICE` | 409 |
| `ERR_ALREADY_DISPOSED` | 409 |
| `ERR_RUN_NOT_COUNTING` | 409 |
| `ERR_ASSET_NOT_IN_SCOPE` | 409 |
| `ERR_ASSET_UNDER_INVENTORY_REVIEW` | 409 |
| `ERR_UNRESOLVED_INVENTORY_ITEMS` | 409 |
| `ERR_UNCOUNTED_LINES` | 409 |
| `ERR_DUPLICATE_TAG` | 409 |
| `ERR_DUPLICATE_RUN_PERIOD` | 409 |
| `ERR_PERIOD_ALREADY_POSTED` | 409 |
| `ERR_PERIOD_GAP` | 409 |
| `ERR_PERIOD_CLOSED` | 409 |
| `ERR_IMPAIRMENT_REVIEW_OPEN` | 409 |
| `ERR_DUPLICATE_SCHEDULE` | 409 |
| `ERR_BELOW_CAPITALIZATION_THRESHOLD` | 422 |
| `ERR_INVALID_AMOUNT` | 422 |
| `ERR_INVALID_SALVAGE_VALUE` | 422 |
| `ERR_INVALID_DISPOSAL_FIELDS` | 422 |
| `ERR_BONUS_NOT_ALLOWED` | 422 |
| `ERR_NO_IMPAIRMENT_INDICATED` | 422 |
| `ERR_INVALID_SCHEDULE_FIELDS` | 422 |
| `ERR_FIELD_IMMUTABLE` | 422 |
| `ERR_STALE_VERSION` | 412 |
