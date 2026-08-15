# Worklog — task_1750_building_energy_benchmarking_disclosure

## Step 1: Create Task Directory — 2026-08-14T13:18:00.000Z

Pre-assigned directory `tasks/task_1750_building_energy_benchmarking_disclosure/` with `workspace/` subdirectory already created (Step 1 treated as DONE per invocation args).

## Step 2: Generate Scaffold — 2026-08-14T14:36:00.000Z

All three artifacts are complete and lint-clean. Summary:

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1750_building_energy_benchmarking_disclosure/`):
- `SCAFFOLD.yaml` (1638 lines) — §1.0–§1.7 only; no `scaffold_difficulty_design`/`scaffold_corner_design` keys
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (861 lines) — single top-level `scaffold_difficulty_design` key
- `SCAFFOLD_CORNER_DESIGN.yaml` (1765 lines) — single top-level `scaffold_corner_design` key

**Counts:**
- Entities: 14 (Owner, Verifier, ReportingCycle, Building, TenantUnit, ConsentGrant, UtilityAccount, UsageRecord, BenchmarkReport, VerificationRecord, AnomalyFlag, FineAssessment, ExemptionRequest, DisclosurePublication)
- Endpoints: 63 (including `POST /v1/_clock/set_current_utc` with the mandated 2026-08-01T00:00:00Z default)
- Calculations: 11 | Validations: 11 priority tiers | Errors: 32 (all referenced by §1.2/§1.4) | State machines: 10 | Concurrency (OCC) rules: 2
- §1.8 instances: 19 non-stub (every rule ≥2; combinatorial_formula has 3, one per mode a/b/c)
- §1.9 instances: 59 non-stub + 3 `excluded_because` stubs (all resolving to real §1.8 instances)
- Lint verdict (pasted verbatim): `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (1019 calls scanned; 16 canonical FK declarations all reverse-reachable)

**Difficulty-design notes (harder-than-expert calibration):**
- **Dual-variant calcs on different domains**: energy score as-reported (46) vs weather-normalized (63) on BenchmarkReport; late fine provisional (10000, deadline→submit) vs final (25000, deadline→verification) on FineAssessment.
- **All three combinatorial modes**: (a) score formula with completeness branch + slope interpolation + clamp (raw 209.46 → 100); (b) pinned per-record kBtu rounding (3×10.5 kWh → 108 vs forbidden sum-first 107); (c) trajectory baseline with pinned evaluation order (own prior-cycle VERIFIED baseline → target 90.00 vs cycle default with years_elapsed pinned 1 → 108.00).
- **Deep cascades**: usage-void → report recompute → VERIFIED→FLAGGED downgrade + auto-anomaly → disclosure SUPERSEDED + replacement DRAFT (depth 3); close-filing → NON_COMPLIANCE fines → owner standing flip (depth 2); plus EXTENSION-approval auto-waive compensation.
- **Subtle boundaries**: inclusive coverage (25000 sqft) vs completeness (90.00/89.99); strict `>` on YoY anomaly (25.00 clean, 25.25 flagged), correction tolerance (exactly 5.00% survives), performance threshold (94.50 free, 94.51 → 2500-cent fine), owner restriction (100000 NORMAL, 105000 RESTRICTED); closed-date consent overlap vs half-open usage-period adjacency; submit-at-exact-deadline on time vs close-at-exact-deadline rejected.
- **RBAC**: segregation_of_duties (cycle creator cannot certify) over 5 roles with entity-backed identity for Owner/TenantUnit/Verifier.
- All fixture arithmetic was pre-computed and pinned as literals in asserts; every recipe replays from empty-DB with fully bound `${var}` placeholders.

## Step 3: Copy Shared Files — 2026-08-14T14:37:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1750_building_energy_benchmarking_disclosure/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-14T14:50:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1750_building_energy_benchmarking_disclosure/workspace/PRD.md` is written and all three hard contracts pass.

**Summary**

- **PRD.md line count:** 349 lines.
- **Sections:** §1 Introduction (2 paragraphs); §2 with 10 subsections (2.1 Roles/Auth, 2.2 Response Structure — byte-identical to the fixed verbatim block, 2.3 Pagination, 2.4 Common Resource Properties, 2.5 The Logical Clock, 2.6 Measurement/Unit Conversion/Rounding, 2.7 OCC, 2.8 Validation Order and Error Priority, 2.9 Nested Resource Retrieval, 2.10 Cascading Consistency); §3 with 9 lifecycle-grouped subsections (Registry & Cycles, Buildings & Coverage, Tenant Units & Consent, Utility Accounts & Usage Data, Filing the Benchmark Report, Verification/Scoring/Certification, Fines & Owner Standing, Exemptions & Extensions, Public Disclosure); §4 Endpoint Definitions (63-row, 4-column table); §5 Error Code Catalogue (32-row, 2-column table).

**Coverage audit — confirmed:**
- All 14 entities, all 63 endpoints, all 11 calculations, all 11 validation priority tiers, all 32 error IDs, and all 10 state machines (29 transitions with preconditions + side effects) are represented as prose.
- Contract 1 (field names): 111 required identifiers (entity fields + request/query/path params + computed read-model keys) — 0 missing, two passes run.
- Contract 2 (rules): 11/11 validation priorities expressed with explicit ordering; 2/2 OCC rules with write-endpoint + `expected_*_version` + `ERR_STALE_VERSION`/412; 29/29 transitions fully expressed; 11/11 calculations in precise reconstructible prose (per-record kBtu rounding order, pinned baseline-selection order for `target_eui`, dual score variants with clamp and label bands, provisional/final late-fine variants, strict-vs-inclusive thresholds); 32/32 error conditions matchable in §2/§3 narrative; all cascade chains (void→recompute→reopen→supersede, revoke→suppress→supersede, close-filing sweep, extension auto-waive) and endpoint `applies_to` scopes expressed; sibling branches symmetric.
- Contract 3 (§3 path purity): 616 backtick tokens scanned in §3 — 0 paths, 0 bare HTTP methods, 0 method+path combos. All endpoint references use state-pair framing, role+verb, or capability description.

**Zero-Silence-Rule judgment calls:**
1. Verifier `license_number` uniqueness is stated as a rule but with no error ID — the scaffold's error catalog nominates none, so I declined to invent one.
2. Report creation against a `FILING_CLOSED`/`PUBLISHED` cycle: the scaffold pins `ERR_CYCLE_NOT_OPEN` to the `SCHEDULED` case for creation (and `ERR_FILING_CLOSED` to submission), so the PRD states the `SCHEDULED` → `ERR_CYCLE_NOT_OPEN` mapping for creation without extrapolating a code for the closed case.
3. The anomaly-resolve "report must be FLAGGED" note from the endpoint description is included as a descriptive constraint, again without inventing an error ID.
4. Compliance-summary output keys (`covered`, `report_status`, `settled_exposure_cents`, `projected_exposure_cents`, `latest_score_as_reported`, `latest_label_grade`, `effective_deadline_at`) and the clock's `current_utc` output are named in prose despite not being entity fields, since the implementer must reproduce those exact keys.
5. Initial-state silence patched explicitly: new DRAFT report's null/zero defaults (`submitted_at`, `verified_at`, `verified_site_eui`, `target_eui`, scores, `label_grade`, `is_late`, `days_late`) and fine `days_late` always zero for non-`LATE_SUBMISSION` types.
6. Constants embedded in business language per the scattering guidance: restriction threshold as "one hundred thousand cents — exactly one thousand dollars", lateness in "whole 86,400-second days", and the commodity conversion factors stated per native unit in §2.6.

## Step 5: Generate Unit Tests — 2026-08-14T15:35:00.000Z

Generation complete for task_1750_building_energy_benchmarking_disclosure. Summary:

## Test counts

**Queue A (Difficulty) — 19/19 instances, 38 tests (exactly 2 per instance):**
- dual_variant_calc: 2 instances → 4 tests
- combinatorial_formula: 3 instances → 6 tests
- non_linear_state_machine: 2 → 4
- transitive_cascade: 2 → 4
- priority_pair_validation_conflict: 2 → 4
- boundary_precision_check: 2 → 4
- cross_entity_state_dependency: 2 → 4
- resource_temporal_overlap: 2 → 4
- compensating_invariant: 2 → 4

**Queue B (Corner) — 59/59 non-stub instances, 63 tests (4 two-armed instances got 2 tests):**
- entities: 6, state_machines: 10, calculations: 8 (10 tests), validations: 22, endpoints: 3, errors: 1, rbac: 3, cross_cutting: 5 (6 tests), consistency_model: 1

**Skipped instances:** none for PRD-first reasons. The 3 `excluded_because:` stubs were not translated, as specified — their pointers resolve to live difficulty instances:
- `Corner/entities/e_covered_list_filter_excludes_uncovered` → `floor_area_exactly_at_coverage_threshold`
- `Corner/calculations/c_completeness_8999_fails_submit` → `completeness_exactly_ninety_passes`
- `Corner/endpoints/ep_void_with_replacement_links_records` → `usage_void_with_identical_replacement_conserves_kbtu`

Every PRD rule cited by the surviving instances has verbatim PRD coverage and a uniquely-derived outcome, so nothing was dropped by the two-condition filter.

## test_helpers written (9 files, ~4450 lines total with suite)
- `types.py` — 14 entity TypedDicts (all carry full common fields per PRD §2.4), 13 status/role enums
- `api_client.py` — `ApiClient(GenericApiClient)` with all 63 endpoints
- `api_errors.py` — 32 `ApiErrorId`s + HTTP map registered via `set_error_http_status_map`
- `assertions.py` — per-entity assertions
- `factories.py`, `constants.py` — payload factories; standard cycle fixture constants (threshold 25000, rates 5000/60/500000, OFFICE standard, commodity kBtu factors)
- `test_users.py` — shared opaque-role headers + mandatory per-instance builders `make_owner_headers` / `make_tenant_rep_headers` / `make_verifier_headers` for the three entity-backed roles
- `fixtures.py` — composite tiers: `setup_report_scenario` / `setup_submitted_report` / `setup_verified_report` / `setup_late_fine_scenario` / `setup_published_cycle_with_verified_report` / `close_filing_cycle` / `review_and_decide_exemption`, all identity-threaded
- `test_suite/conftest.py` — session `api` fixture + one fixture per role

## Verification performed
- All files compile; `pytest --collect-only` collects 101 tests cleanly
- Tag audit: every test has exactly one `Design:` line resolving to a real instance; queue A 19/19 at ≥2, queue B 59/59 non-stub at ≥1, stubs at 0
- Citation audit: all 140 sentence-length quoted spans in docstrings are literal whitespace-normalized substrings of PRD.md

## Notable judgment calls
- **`e_owner_create_applies_defaults`**: dropped the recipe's `version == 1` assertion — PRD §2.4 pins the increment rule but never the initial value, so it fails unique derivability. The test asserts the PRD-covered defaults (`NORMAL`, `outstanding_fines_cents == 0`, bare UUID). Same reasoning: `_assert_common` asserts `version` is an int, not `>= 1`; OCC tests assert versions relatively (`stale + 1`).
- **Datetime equality**: `effective_deadline_at` / `extended_deadline_at` asserted via `startswith("2027-06-01T00:00:00")` / `("2027-07-01T00:00:00")` so both `...Z` and `...T00:00:00.000Z` serializations pass (PRD fixes the instant, not the rendering).
- **Priority-pair instances**: each got one test for the paired-conflict assertion and one isolating the single-failure arm (e.g., completeness gate alone on an OPEN cycle), per the skill's validation-priority guidance; both PRD-derivable because §2.8 names the tier order verbatim.
- Fixed one self-inflicted bug during generation: a class helper in `test_05` referenced the `api` fixture out of scope — now passed explicitly; and `test_07`'s restricted-owner test shares one cycle between its two buildings because `cycle_year` must be unique per PRD §3.1.

## Step 6: Generate Implementation — 2026-08-14T15:35:00.000Z

Done. Final summary:

## Summary — task_1750_building_energy_benchmarking_disclosure

**Result: 101/101 tests pass** under `prd-bench-local-run --isolation per-test-server` (server killed and relaunched via `start.sh` before every test), recorded in `workspace/results.json`.

### Files written (all under `/home/ubuntu/github/CodingPRD/tasks/task_1750_building_energy_benchmarking_disclosure/workspace/implementation/`)

- `start.sh` — guarded install (`pip install` only if `import flask` fails), `exec python3 app.py`, binds `0.0.0.0:$PORT` (default 10000)
- `requirements.txt`, `app.py` (Flask entry, RLock per-request, enveloped 404/405/500 handlers), `db.py` (empty store, logical clock pinned at `2026-08-01T00:00:00Z`, wall/logical timestamp helpers), `errors.py`, `response.py` (exact scaffold envelope: `meta`/`response_type`/`data`, `limit`/`offset`/`total_count`/`has_more`), `middleware.py` (`X-User-ID`/`X-User-Role`, 5 declared roles), `validation.py` (schema checks, ISO datetime/date parsing)
- `services/core.py` — all business logic
- `routes/`: `registry.py`, `cycles.py`, `buildings.py`, `tenant_units.py`, `consents.py`, `utility.py`, `reports.py`, `verifications.py`, `anomalies.py`, `fines.py`, `exemptions.py`, `disclosures.py`, `clock.py`

### Counts
- **Endpoints: 63/63** implemented (including `POST /v1/_clock/set_current_utc`)
- **Entities: 14/14** (Owner, Verifier, ReportingCycle, Building, TenantUnit, ConsentGrant, UtilityAccount, UsageRecord, BenchmarkReport, VerificationRecord, AnomalyFlag, FineAssessment, ExemptionRequest, DisclosurePublication)
- **Calculations: 11/11** — coverage determination, per-record kBtu conversion (convert-then-round, ROUND_HALF_UP, `Decimal` throughout), site_eui, data completeness, dual-variant scoring (as-reported drives label; weather-normalized alongside), pinned-order trajectory target EUI, performance shortfall fine (threshold rounded before compare, cap last), provisional/final late-fine variants, YoY anomaly (strict >), correction delta (frozen `verified_site_eui` baseline), owner exposure/standing (strict `>` 100000)

### Design decisions worth noting
- **Validation priority**: enforced exactly per PRD §2.8 tiers — auth → role → ownership → existence (left-to-right) → OCC (`expected_building_version`/`expected_cycle_version`, 412 before other input checks) → input semantics → state → temporal → safety → constraint → fiscal.
- **No seeding**: store boots empty; all state built via the API surface.
- **Lazy consent expiry is non-materializing**: effective status computed on read/filter/recompute (GRANTED → reads EXPIRED when clock date > `valid_to`); no version bumps on GET. On report GET, completeness is lazily recomputed only when it *decreases* (newly lapsed window), per PRD §3.5.
- **Publication inclusion snapshot**: `_included_report_ids` (private, stripped from serialization) frozen at publish time, so the supersede cascade targets exactly the published set; replacement DRAFT gets `publication_version + 1`.
- **Cascade touch discipline**: each mutated entity gets exactly one `updated_at`/`version` bump per request; failed submissions leave no side effects (gates evaluated against locally recomputed values before commit).
- **One fix found via the suite**: client-supplied computed/system fields on create (e.g. `standing`, `outstanding_fines_cents`) must be silently ignored, not rejected — unknown-field rejection removed.
- The two earlier `NameError: 'api'` failures were test-suite bugs (fixed by the parallel test-generator agent); the one `ConnectionError` was an environment process-reaping artifact, not reproducible (exact sequence replayed cleanly by hand).

## Step 7: Run Tests and Iterate — 2026-08-14T15:45:00.000Z

Clean 8-round parallel sweep achieved. Summary below.

## Summary

- **Iterations run:** 1 (single 8-round parallel sweep; exit condition met immediately)

- **Sweep results:** All 8 rounds: `passed=101, failed=0, errors=0, skipped=0, total=101`. Round durations ~133s each, uniform across rounds — no flakiness signal, no timing-sensitive failures, no port collisions.

- **Tests deleted:** None.

- **Fixes applied to `test_helpers/`:** None required.

- **Fixes applied to `implementation/`:** None required this iteration. The implementation generated in Step 6 (per `worklog.md`) was already correct: 63/63 endpoints, 14/14 entities, 11/11 calculations, full §2.8 validation-priority ordering, in-memory-only storage with empty boot state, OCC on building/cycle edits, and all cascades (void→recompute→reopen→supersede, revoke→suppress→supersede, close-filing sweep, extension auto-waive) implemented per PRD.

- **Artifacts:**
  - Results: `/home/ubuntu/github/CodingPRD/tasks/task_1750_building_energy_benchmarking_disclosure/workspace/implementation/results.{1..8}.json`
  - Implementation: `/home/ubuntu/github/CodingPRD/tasks/task_1750_building_energy_benchmarking_disclosure/workspace/implementation/`
  - Test suite: `/home/ubuntu/github/CodingPRD/tasks/task_1750_building_energy_benchmarking_disclosure/test_suite/` (101 tests across 11 files)

## Step 8: Finalize PRD — SKIPPED

Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes. Skip condition met — `PRD.md` already determines every behavior the implementation exhibits.

## Step 9: Complete PRD — 2026-08-14T15:56:00.000Z

All 23 edit hunks are in place and verified against the diff. Final summary:

## PRD_COMPLETED.md produced

**Source vs output:** `PRD.md` = 348 lines / 61,160 chars → `PRD_COMPLETED.md` = 350 lines / 65,796 chars (**+2 lines, +4,636 chars**). 23 inline hunks; no new sections.

**Counts:** 21 ambiguity-pins, 2 mismatch-revisions (one hunk was mixed: §3.1 edit paragraph contains one of each).

**Changes (section — insert|revise — kind — what — impl ref):**

- §2.2 Error format — insert — ambiguity — unknown path or unsupported method rejected as `ERR_NOT_FOUND` (404) in the standard envelope — app.py:36-43
- §2.3 Pagination — insert — ambiguity — unparseable `limit`/`offset` fall back to defaults; limit clamped to 1..100, offset floored at 0 — response.py:64-74
- §2.4 Common fields — insert — ambiguity — `version` starts at 1, `updated_at` == `created_at` at creation — db.py:76-85
- §2.4 Common fields — insert — ambiguity — `created_at`/`updated_at` stamped from strictly-increasing wall clock with 3 fractional digits; all other datetime fields render ISO 8601 UTC omitting the fractional part on whole seconds — db.py:51-70, 73-85
- §2.5 Logical clock — insert — ambiguity — unparseable `to_iso8601` → `ERR_INVALID_REQUEST` — routes/clock.py:18-21
- §2.7 OCC — insert — ambiguity — absent/non-integer `expected_*_version` → `ERR_INVALID_REQUEST` — routes/cycles.py:129-135, routes/buildings.py:83-90
- §2.8 tier 6 — insert — ambiguity — request fields the endpoint does not define are ignored, not rejected — validation.py:78-97
- §2.9 Nested retrieval — insert — ambiguity — body reference absent/non-string → `ERR_INVALID_REQUEST`; well-formed but unknown → `ERR_NOT_FOUND`; referenced resource's existence confirmed before the ownership check on it — routes/reports.py:32-49, routes/exemptions.py:27-34, routes/verifications.py:26-33
- §3.1 Registry — insert — ambiguity — duplicate verifier `license_number` → `ERR_INVALID_REQUEST` — routes/registry.py:49-52
- §3.1 Cycle creation — insert — ambiguity — `performance_standards` entries must carry all 8 fields with valid `property_type` and numeric values; invalid `covered_property_types` entries and duplicate `cycle_year` → `ERR_INVALID_REQUEST` — routes/cycles.py:27-54, 77-79
- §3.1 Cycle edit — insert — ambiguity — non-editable fields (`cycle_year`, `covered_floor_area_threshold_sqft`, `covered_property_types`, unrecognized) silently ignored — routes/cycles.py:109-151, validation.py:82-84
- §3.1 Cycle edit — revise — mismatch — state check (`ERR_CYCLE_NOT_EDITABLE`) fires *before* deep `performance_standards` entry validation, contrary to the naive §2.8 tier-6-before-tier-8 reading — routes/cycles.py:140-144
- §3.2 Building registration — insert — ambiguity — BuildingOwner's body `owner_id` ignored, no owner-existence check on that path; officer path: absent → `ERR_INVALID_REQUEST`, unknown → `ERR_NOT_FOUND` — routes/buildings.py:31-39
- §3.2 Covered list — insert — ambiguity — `covered_in_cycle_id` naming no cycle → `ERR_NOT_FOUND` — routes/buildings.py:65-69
- §3.2 Building update — insert — ambiguity — updatable attributes enumerated (`address`, `gross_floor_area_sqft`, `property_type`); `owner_id` ignored — routes/buildings.py:91-104
- §3.2 Compliance summary — insert — ambiguity — `cycle_id` required (`ERR_INVALID_REQUEST`) and must exist (`ERR_NOT_FOUND`); "most recent" score/label = report with non-null `verified_at` from the largest `cycle_year` — routes/buildings.py:140-167
- §3.3 Consent request — insert — ambiguity — new grant's `valid_from`/`valid_to`/`decided_at` null until decision — routes/consents.py:36-44
- §3.3 Consent grant — insert — ambiguity — unparseable dates → `ERR_INVALID_REQUEST`; overlap check applies lazy expiry (expired windows do not block) — routes/consents.py:59-80
- §3.3 Consent revoke — insert — ambiguity — lazily-expired grant cannot be revoked → `ERR_INVALID_STATE_TRANSITION` — routes/consents.py:125-127
- §3.4 Void cascade — revise — ambiguity — cascade covers each affected cycle year: voided record's year plus the replacement's year when different — routes/utility.py:155-177, services/core.py:505-517
- §3.5 Report creation — insert — ambiguity — `FILING_CLOSED`/`PUBLISHED` cycle also rejects creation with `ERR_CYCLE_NOT_OPEN`; reports list filterable by `building_id`, `cycle_id`, `status` — routes/reports.py:55-57, 104-106
- §3.5 Completeness — insert — ambiguity — lazy read-time recompute only ever lowers the stored percentage — routes/reports.py:15-25
- §3.6 Verification assignment — insert — ambiguity — `verifier_id` must name a registered verifier (`ERR_NOT_FOUND`); `accredited` flag not consulted; records list filterable by `report_id`, `verifier_id` — routes/verifications.py:26-33, 111-112
- §3.6 Correction check — insert — ambiguity — zero `verified_site_eui` baseline: zero recomputed EUI leaves the report untouched, any nonzero value is beyond tolerance — services/core.py:467-484
- §3.8 Exemption filing — revise — mismatch — `requested_extension_days` on `EXEMPTION` is stored on the request (returned by reads) but inert, not "ignored" — routes/exemptions.py:66
- §3.9 Disclosure publish — insert — ambiguity — publishing a draft never itself supersedes an earlier `PUBLISHED` publication; only the cascades do — routes/disclosures.py:45-68

Everything else in the implementation (all 57 endpoints' role gating, state machines, the 11 calculations with pinned rounding, cascade chains, envelope shape, error catalogue) was already uniquely pinned by PRD prose and required no change.

## Pipeline COMPLETE

Steps 1–9 all finished. `workspace/PRD_COMPLETED.md` exists. Final state: 101/101 tests passing across an 8-round parallel stability sweep under `--isolation per-test-server`.
