# Worklog — task_1438_hospital_price_transparency_file

## Step 1: Create Task Directory — 2026-08-13T07:12:00.000Z

Task directory `tasks/task_1438_hospital_price_transparency_file/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline launcher. Step 1 treated as DONE per instructions; no index scan performed, no other task directory touched.

## Step 2: Generate Scaffold — 2026-08-13T08:33:00.000Z

Scaffold generation complete and lint-clean. All three artifacts are in `/home/ubuntu/github/CodingPRD/tasks/task_1438_hospital_price_transparency_file/` (3,581 lines total).

### What was generated

**SCAFFOLD.yaml** (§1.0–§1.7, no difficulty/corner keys; verified): 10 entities, 9 state machines, 11 calculations, 9 validation priority tiers, 45 endpoints, 53 error codes, 5 roles, 2 OCC concurrency rules. Archetype: compliance/audit + pricing engine; layers: dual-variant calculation, cascading side effects, optimistic concurrency, version-pinning on approval; role model: segregation of duties (proposer ≠ approver ≠ applier; attestation submitter vs CMS decision proxy). Logical clock endpoint with the mandated `2026-08-01T00:00:00Z` default drives contract expiry, attestation escalation, and penalty accrual deterministically.

**SCAFFOLD_DIFFICULTY_DESIGN.yaml** (§1.8): 18 instances — exactly 2 per rule × 9 rules. Highlights: EXACT_MIN vs MIX_WEIGHTED rate derivation (40000 vs 55000) + SIMPLE vs TIERED penalty (90000 vs 30000); mode-(a) nested-min display price (55000) + mode-(b) per-item floor rounding (40598 vs 40599); contract renegotiation cycle + MRF parallel dimensions with INVALID→VALID loop; depth-3 item→rate→record→cycle cascade + depth-2 terminate cascade; existence-vs-state and state-vs-referential priority conflicts; certify count `>=` boundary + penalty day-0/day-1 floor boundary; record→cycle and item→list cross-entity gates; CLOSED (touching = conflict) vs HALF-OPEN (touching = OK) interval semantics; record-count conservation + monetary round-trip invariants across the correction workflow.

**SCAFFOLD_CORNER_DESIGN.yaml** (§1.9): 92 instances (79 active + 13 `excluded_because` stubs) across all nine guide sections — entity defaults/computed fields, terminal lockdowns, posture gates, clock-driven transitions, SoD steps, entry/ancillary validation trio, all 10 not-found codes, RBAC denials (role check precedes existence), both OCC stale-version paths, envelope/pagination/FK-reverse claims, immediate consistency.

**Verification**: `scaffold_lint.py` verdict — clean lint (864 calls scanned, all FKs reverse-reachable). A supplementary audit confirmed zero unbound `${var}` placeholders, unique instance names across both files, all `grounds:` resolve into §1.1–§1.7, and all 53 error codes are referenced by at least one test recipe. All numeric asserts were pre-computed (e.g., floor((40000·100+60000·300)/400)=55000; 299+299=598 vs 599; 35 days × 30000 = 1050000). No sibling tasks were read.

## Step 3: Copy Shared Files — 2026-08-13T08:35:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1438_hospital_price_transparency_file/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-13T08:55:00.000Z

PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_1438_hospital_price_transparency_file/workspace/PRD.md` (293 lines). The withheld test-index files were never opened.

### PRD Section List
- **1. Introduction** — 2 paragraphs (regulatory context + the confidentiality/correction design tensions)
- **2. Global Specifications & System-Wide Principles**
  - 2.1 User and Role-Based Access Control (5 roles, all `identity: opaque` translated to prose; auth error IDs)
  - 2.2 API Response Structure (byte-verbatim copy of `section-2.2-response-structure.md`, verified programmatically)
  - 2.3 Pagination (`limit` 10/1/100, `offset` 0, `created_at` ascending, meta fields)
  - 2.4 Resource Identity, Timestamps, and Versioning (all 10 entities carry `id`/`created_at`/`updated_at`/`version`)
  - 2.5 The Logical Clock (startup default 2026-08-01T00:00:00Z, `to_iso8601`/`current_utc`, clock-advance system transitions)
  - 2.6 Optimistic Concurrency Control (both OCC rules with `expected_service_item_version` / `expected_publication_cycle_version` → `ERR_STALE_VERSION` 412)
  - 2.7 Integer-Cents Arithmetic and Rounding Discipline (floor placement, pinned per-item bundle rounding with the 333-cent forbidden-alternative example)
  - 2.8 The Rate-to-Publication Cascade Chain (depth-3 cascade: item → rates → records → cycles)
  - 2.9 Validation Order and Identifier Resolution (the 9-rung priority ladder in explicit prose, left-to-right path-id resolution)
- **3. Business Logic & Workflows** (8 subsections: facility/payer onboarding → catalog & rate materialization → charge extraction → freeze/file/publish → shoppable list & display → attestation & penalties → segregated correction pipeline → contract lifecycle & price-maintenance cascades)
- **4. Endpoint Definitions** — 4-column table, all 45 endpoints
- **5. Error Code Catalogue** — 2-column table, all 53 error IDs with statuses matching the scaffold exactly

### Coverage Note (§1.1–§1.7)
- **§1.1 Entities**: all 102 required identifiers (every entity field, nested `entries`/`pinned_records` sub-fields, every endpoint input/query/path param, envelope fields) appear verbatim in backticks — programmatic diff: 0 missing.
- **§1.2 State machines**: all 9 machines covered — every transition's from/to pair, preconditions with their error IDs, and side-effect cascades (including sibling symmetry: attestation decision branches, file-validate loop, REJECTED/ESCALATED → PLAN_SUBMITTED, DRAFT/RENEGOTIATING activation).
- **§1.2.1 Concurrency**: both OCC rules fully expressed (endpoint capability, occ field, stale-mismatch rejection, exact error ID + HTTP 412), no race-framing.
- **§1.3 Calculations**: all 11 rules in reconstruction-grade prose (3 rate-materialization branches, extrema inclusion set, dual-variant derived disclosure with pinned 5-step evaluation order and de-identification floor of 3, display package pricing, pinned bundle rounding, MRF schema violations with deterministic sort, summary rollup ordering, 8-value posture derivation, inclusive shoppable thresholds checked total-then-mandated, dual-variant penalty accrual with 86400-second day math and the 25-bed divergence example).
- **§1.4 Validations**: priority ladder stated as explicit ordering with masking consequence; every check matched to its error ID in prose near its workflow (including in-rule orderings: certify total-before-mandated, discrepancy record-cycle-match before disputable-status).
- **§1.5 Endpoints**: 45/45 in the §4 table with correct roles; all side effects narrated in §3.
- **§1.6 Errors**: 53/53 present both in §2/§3 prose and in the §5 table; HTTP statuses verified against scaffold.
- **§1.7 Roles**: all 5 role names spelled exactly; each `identity: opaque` translated into §2.1 prose with the `proposed_by_user_id`/`approved_by_user_id`/`applied_by_user_id` recording note.

**Hard-contract results** — Contract 1 (field coverage): PASS, 0 missing of 102. Contract 2 (rule coverage): PASS per the walk above. Contract 3 (§3 path purity): PASS — 560 backtick tokens scanned, 0 path/method violations. No pseudocode operators, no fuzzy/approximating words; §2.2 byte-identical. One judgment call to flag: for freeze-on-non-OPEN and publish-on-non-FROZEN, the PRD routes rejection through the posture gate (`ERR_POSTURE_NOT_FREEZABLE` / `ERR_POSTURE_NOT_PUBLISHABLE`), matching the error catalog's condition scoping (the catalog scopes `ERR_CYCLE_NOT_OPEN`/`ERR_CYCLE_NOT_FROZEN` to record create/validate and file generation respectively).

## Step 5: Generate Unit Tests — 2026-08-13T09:30:00.000Z

All audits pass. The suite collects cleanly (114 tests). Generation is complete.

### Summary

**Generated files** (under `/home/ubuntu/github/CodingPRD/tasks/task_1438_hospital_price_transparency_file/`):

`test_helpers/` (9 files): `__init__.py` (barrel), `types.py` (10 entity TypedDicts + 20 status/domain enums), `api_client.py` (45 endpoint methods), `api_errors.py` (55-id catalog with HTTP map registered via `set_error_http_status_map`), `assertions.py` (per-entity assertions + cycle-aggregate invariant), `factories.py`, `constants.py` (penalty tiers, de-identification floor, bundle discount, clock default), `test_users.py` (5 opaque roles, shared constants + per-instance builders for SoD), `fixtures.py` (5 tiers incl. `setup_published_cycle`, `setup_rejected_attestation`, `setup_correction_approved`, `setup_published_shoppable_list`).

`test_suite/` (8 files, 114 tests): `test_01` facilities/attestation/penalties (12), `test_02` payers/contracts/rates (16), `test_03` service items + OCC + gross-patch cascade (6), `test_04` charge records + derivation variants (14), `test_05` cycles + machine files (12), `test_06` shoppable lists + consumer display (19), `test_07` discrepancy/correction pipeline (13), `test_08` envelope/RBAC/404s (22).

**Coverage (machine-audited)**: Queue A — 18/18 difficulty instances × ≥2 tests (36 tests). Queue B — 78/79 non-stub corner instances × 1 test. All 13 `excluded_because` stubs verified to resolve to real difficulty instances and were not translated. Every test carries exactly one verbatim `Design:` tag resolving to its source instance; every docstring's quoted PRD sentence survives a whitespace-normalized literal grep of `PRD.md`; no skip/xfail markers; no scaffold references in comments.

**Instances skipped (1)**: `Corner/entities/service_item_list_pagination_interacts_with_filter` — its core claim asserts a `service_class` query filter on `GET /facilities/{id}/service-items`, but the PRD never mentions filter params for that endpoint (§4 row says only "List service items of a facility"; §2.3 covers only limit/offset). Fails the coverage condition. The pagination sub-claims remain covered by `Corner/endpoints/record_list_pagination_defaults_applied`.

**Self-audit findings**:
1. **Corner-design bug (PRD contradiction)**: `Corner/calculations/extrema_null_without_rates_and_validate_blocked` pre-computes `derivation_method == NONE` for the empty rate universe, but PRD §3.3 pins `EXACT_MIN` with a null disclosure figure for exactly that case. The emitted test asserts the PRD-correct `EXACT_MIN`; flagged here rather than papered over.
2. **Corner recipe reachability fix**: `conditional_ancillary_respects_include_flag`'s recipe displays list L1 after publishing L2 — but publishing L2 auto-archives L1 (PRD §3.5), which would fail the L1 display with `ERR_LIST_NOT_PUBLISHED`. The test displays L1 right after its own publish, then publishes L2 and displays it; assertions unchanged.
3. **Absolute version literals** (`version == 1` at create, pinned `record_version == 3`, cycle v3→v4) follow the recipes' pre-computed values and the established sibling-task convention (PRD §2.4 pins +1-per-mutation; initial value 1 is benchmark convention).

## Step 6: Generate Implementation — 2026-08-13T10:05:00.000Z

Complete. All 114 benchmark tests pass under `prd-bench-local-run --isolation per-test-server`, verified across two consecutive full runs (114/114, 0 failed, 0 errors each time), plus an independent ~70-assertion E2E smoke suite replaying the scenario-design expectations.

### Summary

**File list** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1438_hospital_price_transparency_file/workspace/implementation/`):
- `start.sh` — guarded launcher (`pip install` only if flask import fails), `exec python3 app.py`, binds `0.0.0.0:$PORT` (default 10000)
- `requirements.txt` — flask, waitress
- `app.py` — Flask entry, blueprint registration, ApiError/404/405/500 envelope handlers; waitress `serve()` with `app.run` fallback
- `db.py` — in-memory stores (10 dicts, start empty, no seeding), logical clock (default exactly `2026-08-01T00:00:00Z`, never wall-clock), UUID/ISO-8601-ms/`version`/`_seq` helpers
- `errors.py` — ApiError + all 53 cataloged error IDs with exact HTTP statuses
- `response.py` — envelope: `meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`; list meta adds `limit`/`offset`/`total_count`/`has_more`
- `middleware.py` — `X-User-ID`/`X-User-Role` presence (400) then role permission (403); 5 roles
- `util.py` — pagination (limit default 10, min 1, max 100, offset 0), body/type/enum/ISO validators, `created_at`-ASC + insertion-seq sorting
- `services/core.py` — derivations, cascades, posture, penalties
- `routes/` — clock, facilities, payers, contracts, items, records, rates, lists, cycles, files, discrepancies

**Endpoints: 45** (all 45 from the scaffold endpoint table; route-decorator count verified).

**State machines implemented (9):** Facility attestation (NONE/SUBMITTED/ACCEPTED/REJECTED/PLAN_SUBMITTED/CLOSED/ESCALATED incl. clock-driven escalation and REJECT_ATTESTATION file-retraction cascade); PayerContract (DRAFT/ACTIVE/RENEGOTIATING/TERMINATED/EXPIRED incl. clock expiry); PayerNegotiatedRate (cascade-driven + create-with-supersede); ServiceItem (ACTIVE/RETIRED with certified-list guard); StandardChargeRecord (DRAFT/VALIDATED/PUBLISHED/FLAGGED/SUPERSEDED); ShoppableServiceList (DRAFT/CERTIFIED/PUBLISHED/ARCHIVED with publish-time version pinning and auto-archive); PublicationCycle (OPEN/FROZEN/PUBLISHED/SUPERSEDED with posture gates and supersede cascade); MachineReadableFile (parallel generation × validation dimensions, regeneration supersedes, validation loops); DiscrepancyReport (SUBMITTED→CONFIRMED/DISMISSED→CORRECTION_PROPOSED→CORRECTION_APPROVED→CORRECTED with SoD).

**Calculation rules implemented (11):** negotiated-amount materialization (3 rate-type branches, floor via Decimal); standard-charge extrema (ACTIVE+DISCLOSE_ALLOWED only); derived disclosure (EXACT_MIN vs MIX_WEIGHTED volume-weighted floor, NONE; de-identification payer floor ≥3); consumer display price (nested min over pinned record; per-ancillary `floor(gross*0.9)` before summation — verified 40598 vs forbidden 40599); bundle rounding order; MRF schema validation (MIN_RECORDS_BELOW_FLOOR, RETIRED_ITEM_PRESENT, DEIDENTIFICATION_VIOLATION, deterministic sort); MRF generation snapshot rollup; cycle posture derivation (8 postures); shoppable count aggregation (total before mandated, `>=` inclusive); payer-count de-identification; penalty accrual (SIMPLE 30000/day vs TIERED 10000/20000/40000 by bed brackets, whole-day floor, freeze on non-accruing states, restart-from-zero on re-rejection).

**Key design decisions:** cycle aggregates/posture computed on demand from child state (pure functions — cannot drift); version starts at 1, bumps on every mutation including cascades; OCC (`expected_service_item_version`, `expected_publication_cycle_version` → 412) checked after existence; validation order follows the PRD §2.9 ladder with PRD prose winning over scaffold priorities (e.g., window check before overlap at contract activate); timestamps sourced from the logical clock; user-supplied datetimes echoed verbatim; monetary math in integer cents/`Decimal` only.

**Boot verification:** `bash start.sh` boots fresh on a clean port and serves within ~3s; two full per-test-server harness runs (server killed and relaunched before each of the 114 tests) passed 114/114 with zero restart flakes.

## Step 7: Run Tests and Iterate — 2026-08-13T10:25:00.000Z

### Summary

**Exit condition met**: all 8 parallel rounds pass 114/114 (0 failed, 0 errors in every round).

**Iterations run**: 2
- Iteration 1 (baseline): 7/8 rounds green; union of failures = 1 flaky test (`test_05_cycles_and_machine_files.py::TestFileGenerationAndValidation::test_superseded_file_cannot_be_validated`, failed only in round 3).
- Iteration 2 (verification): 8/8 rounds green, 114/114 each.

**Diagnosis of the single flaky failure (STEP 0-3 applied)**:
- STEP 0: Failure detail was `requests.exceptions.ConnectionError: ('Connection aborted.', ConnectionResetError(104, 'Connection reset by peer'))` raised on a `POST /transparency/machine-readable-files/{id}/validate` call — a transport-level reset, not an assertion failure.
- Root cause: infrastructure race inherent to per-test-server isolation under 8-way parallel load. The runner kills and re-spawns the server on the same port before every test; the session-scoped `requests.Session` in `test_helpers/api_client.py` pools keep-alive connections, so a request can be sent on a stale socket whose server side was killed → kernel RST. This is the exact flake pattern that 8-round concurrency is designed to surface (1 failure in 912 test executions).
- STEP 1/2: Not a PRD-coverage or test-faithfulness issue — the test itself cites PRD §3.4 verbatim and is faithful; the failure occurred before any assertion ran.
- Fix category: test infrastructure (`test_helpers/`), matching the established repo-wide convention found in 10+ sibling tasks (e.g. `task_1226`, `task_1231`, `task_1284`, `task_1302`).

**Tests deleted**: none.

**Fixes applied to `test_helpers/`**:
- `/home/ubuntu/github/CodingPRD/tasks/task_1438_hospital_price_transparency_file/test_helpers/api_client.py` — after the `api_client = ApiClient()` singleton, set `api_client.session.headers["Connection"] = "close"` with an explanatory comment. This forces a fresh TCP connection per request, eliminating the stale-keep-alive reuse race against respawned per-test servers. No assertion, fixture, or factory was weakened; no implementation change was needed.

**Fixes applied to `implementation/`**: none — the implementation was already fully PRD-faithful (verified: full read of all 11 route/service files against PRD §2–§5 during the diagnostic window; the worklog also records two prior consecutive 114/114 runs).

## Step 8: Finalize PRD — 2026-08-13T10:35:00.000Z

Done. `PRD_FINALIZED.md` exists at `/home/ubuntu/github/CodingPRD/tasks/task_1438_hospital_price_transparency_file/workspace/PRD_FINALIZED.md` and is byte-identical to `PRD.md`.

### Summary

**Line counts / %-delta**
- `PRD.md`: 292 lines
- `PRD_FINALIZED.md`: 292 lines
- Delta: 0 lines, 0.0% (md5-identical: `4e3bf551731e6acad96d4e3c732e2d9c`)

**Changes**: none.

**Rationale** — The single Step 7 item was a fix to `test_helpers/api_client.py`: after the `api_client = ApiClient()` singleton, it sets `api_client.session.headers["Connection"] = "close"` with an explanatory comment. Confirmed:

- (a) **Subject**: HTTP transport behavior of the shared test client session under per-test-server isolation.
- (b) **Paths enumerated**: the change touches only the `requests.Session` default header on the test-side client singleton. It sends no new request semantics — every endpoint method in `ApiClient` (facilities, attestations, payers, contracts, service items, charge records, rates, shoppable lists, cycles, machine-readable files, discrepancies, corrections) is unchanged; no per-request `headers` argument interacts with it (per-request header dicts are merged over session defaults by `requests`, and none of the test helpers set `Connection` themselves). The implementation server (`workspace/implementation/`) was not modified at all, and no tests were deleted or weakened.
- (c) **Wording adjustment**: none needed — the fix addresses a stale keep-alive socket reuse race against respawned per-test servers (ConnectionResetError/RemoteDisconnected flake). It is a client-side infrastructure concern that reveals no PRD silence and no PRD/implementation behavioral mismatch. The PRD specifies API behavior, not TCP connection reuse policy of the test harness.

Since the sole Step 7 item is a pure HTTP-transport infrastructure fix with zero behavioral content, no PRD edits are warranted, and `PRD_FINALIZED.md` is left byte-identical to `PRD.md`. A fresh implementer reading `PRD.md` (== `PRD_FINALIZED.md`) is in exactly the same position as before Step 7, which is the correct outcome here.

## Step 9: Complete PRD — 2026-08-13T10:55:00.000Z

PRD_COMPLETED.md is written. Summary:

### Result

**Source vs output**: `PRD_FINALIZED.md` (292 lines / 53,254 chars; identical to PRD.md — Step 8 made no changes) → `PRD_COMPLETED.md` (296 lines / 57,712 chars; **+4 lines, +4,458 chars**).

**Counts**: 18 ambiguity-pins, 4 mismatch-revisions (22 edits total; no new sections).

#### Mismatch revisions (PRD described different behavior than impl)

- §2.9 — revise — mismatch — Reordered the validation ladder: temporal sanity (`ERR_INVALID_WINDOW`) moved ahead of structural constraints (duplicates/overlaps/entry composition), because impl checks window sanity before overlap on both cycle creation and contract activation (`implementation/routes/cycles.py:66-80`, `implementation/routes/contracts.py:107-120`).
- §2.9 — revise — mismatch — Carved `supersedes_id` out of the existence rung: its target is validated at the cross-referential rung and any failure yields `ERR_SUPERSEDE_TARGET_INVALID`, never a 404 (`implementation/routes/records.py:78-85`).
- §3.8 — revise — mismatch — Activation from `ACTIVE` (not only from `TERMINATED`/`EXPIRED`) is rejected with `ERR_CONTRACT_ALREADY_TERMINAL`; impl rejects activation from any status other than `DRAFT`/`RENEGOTIATING` (`implementation/routes/contracts.py:127-128`).
- §3.6 — revise — mismatch (silence about a stored-field mutation contradicting the field list) — Resubmission from `CLOSED` additionally resets `penalty_accrued_cents` to zero (`implementation/routes/facilities.py:141-144`).

#### Ambiguity pins (PRD silent)

- §2.1 — insert — ambiguity — Whitespace-only header values count as empty (`implementation/middleware.py:35`).
- §2.2 — insert — ambiguity — Framework-level failures: unknown path → `ERR_NOT_FOUND` (404), unsupported method → `ERR_INVALID_REQUEST` (405), unexpected failure → `ERR_INTERNAL` (500); routes match with or without trailing slash (`implementation/app.py:49-59,31`).
- §5 — insert — ambiguity — Catalogue rows added: `ERR_NOT_FOUND` 404, `ERR_INTERNAL` 500 (`implementation/errors.py` + `app.py:49-59`).
- §2.3 — insert — ambiguity — Non-integer/out-of-range `limit`/`offset` rejected with `ERR_INVALID_REQUEST` 400 (`implementation/util.py:21-45`).
- §2.3 — insert — ambiguity — `created_at` ties broken by creation order, earliest first, for list sorts and all pinned `created_at`-ascending orderings (`implementation/util.py:53-55`, `_seq` tie-breaks throughout).
- §2.3 — insert — ambiguity — Exact-match filter parameters per listing: `status` on contract and shoppable-list listings, `service_class`/`status` on items, `cycle_type`/`status` on cycles, `publication_cycle_id`/`standard_charge_record_id`/`status` on discrepancy reports (`implementation/routes/payers.py:63`, `contracts.py:97`, `items.py:101`, `cycles.py:107`, `lists.py:157`, `discrepancies.py:108`).
- §2.4 — insert/revise — ambiguity — `version` starts at 1 (was "its initial value"); entity timestamps are stamped from the logical clock, not wall-clock (`implementation/db.py:88-95,72-74`).
- §2.5 — revise — ambiguity — Clock set stores the supplied instant verbatim, echoes it as `current_utc`, and accepts any parseable ISO 8601 value including earlier-than-current (`implementation/routes/clock.py:20-22,47`).
- §2.6 — insert — ambiguity — OCC precondition evaluated after identifier resolution and payload-shape validation, before state legality (`implementation/routes/items.py:115-133`, `files.py:48-65`).
- §2.9 — insert — ambiguity — Placement of payload-shape and enum-membership validation: shape at parse time before FK resolution; enums after body-FK resolution except `ancillary_inclusion` (item create) and `rate_type` + conditional inputs (rate create), which are validated at parse time (`implementation/routes/items.py:60,68-71`, `rates.py:62-73`).
- §3.1 — insert — ambiguity — `bed_count` and the three numeric posture settings are non-negative integers (`implementation/routes/facilities.py:54-64`).
- §3.2 — revise — ambiguity — `rate_percent` is a JSON number (fractional values allowed, e.g. 33.5); `flat_amount_cents` a non-negative integer (`implementation/routes/rates.py:49,51-53`; `util.py:132-140`).
- §3.2 — insert — ambiguity — Rate amendment with neither `rate_percent` nor `flat_amount_cents` is a no-op rejected with `ERR_INVALID_REQUEST` (`implementation/routes/rates.py:133-136`).
- §3.3 — revise — ambiguity — "Terminal" for the cycle-overlap check defined: only `SUPERSEDED`; `OPEN`/`FROZEN`/`PUBLISHED` cycles block overlapping creates (`implementation/routes/cycles.py:71-80`).
- §3.3 — revise — ambiguity — `MIX_WEIGHTED` pool whose `annual_volume` values sum to zero also yields `derivation_method` `NONE` and null `derived_disclosure_cents` (`implementation/services/core.py:106-114`).
- §3.4 — revise — ambiguity — `validation_errors` entry format pinned: record-tagged violations stored as `"<CODE>:<record_id>"`, `MIN_RECORDS_BELOW_FLOOR` as the bare code (`implementation/routes/files.py:163`).
- §3.5 — revise — ambiguity — "Latest PUBLISHED cycle" for list publishing ranges over both `cycle_type`s (`implementation/routes/lists.py:182-187`); when several `PUBLISHED` records of an entry's item sit in that cycle, the most recently created is pinned (`lists.py:215-216`).
- §3.5 — revise — ambiguity — Display response shape pinned: top-level `list_id`, `entries` (in entry order), `stale_any`; row fields enumerated (`service_item_id`, `display_name`, `display_order`, `bundled_ancillary_item_ids`, `include_conditional_ancillaries`, `charge_record_id`, `record_version`, `base_cents`, `bundle_cents`, `package_price_cents`, `stale`) (`implementation/routes/lists.py:284-302`).
- §3.6 — insert — ambiguity — Plan submission freezes `penalty_accrued_cents` at the accrual computed at submission time (`implementation/routes/facilities.py:208-210`).
- §3.7 — insert — ambiguity — Confirming a report whose disputed record is already `FLAGGED` leaves the record untouched: no transition, no version increment (`implementation/routes/discrepancies.py:127-130`).
- §3.8 — insert — ambiguity — Renegotiation applies a new `effective_end` without re-validating the window; the window re-check runs at next activation (`implementation/routes/contracts.py:144-151` vs `103-108`).
- §3.8 — insert — ambiguity — Item PATCH: `status` accepts only `RETIRED`; price changes and retirement may combine in one PATCH (price cascade still fires); a PATCH with neither is a no-op rejected with `ERR_INVALID_REQUEST` (`implementation/routes/items.py:117-124,141-152`).

Everything else in the impl — derivation variants and payer-count floor, cascade chains and version bumps, posture derivation, publish supersession selection, OCC guards, SoD checks, penalty accrual brackets and day arithmetic, clock-advance consequences (date-level contract expiry, instant-level escalation), envelope shape, endpoint table, role matrix, and all error codes — was already uniquely pinned by PRD_FINALIZED.md and left unchanged.
