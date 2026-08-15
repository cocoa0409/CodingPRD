# Worklog — task_2029_groundwater_sustainability_well_metering

## Step 1: Create Task Directory — 2026-08-15T08:08:00.000Z

Directory `tasks/task_2029_groundwater_sustainability_well_metering/` and `workspace/` pre-created by the pipeline launcher (per invocation instructions; no index scan performed).

## Step 3: Copy Shared Files — 2026-08-15T08:09:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_2029_groundwater_sustainability_well_metering/workspace/INSTRUCTION.md`.

## Step 2: Generate Scaffold — 2026-08-15T08:50:00.000Z

Scaffold generation complete. All three artifacts written and lint-clean.

## Files written
- `/home/ubuntu/github/CodingPRD/tasks/task_2029_groundwater_sustainability_well_metering/SCAFFOLD.yaml` — §1.0–§1.7 (no design keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_2029_groundwater_sustainability_well_metering/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level `scaffold_difficulty_design:` (§1.8)
- `/home/ubuntu/github/CodingPRD/tasks/task_2029_groundwater_sustainability_well_metering/SCAFFOLD_CORNER_DESIGN.yaml` — single top-level `scaffold_corner_design:` (§1.9)

## Design summary
- **Profile**: compliance_audit (primary) × quota_allocation (secondary); layers: dual-variant calculation, rate/threshold triggers, cascading side effects, optimistic concurrency; flat topology; posture_driven gating (published basin condition gates fees/curtailment/transfer settlement); segregation-of-duties role model; immediate consistency; fixed logical clock defaulting to 2026-08-01T00:00:00Z.
- **Counts**: 8 entities, 7 state machines, 9 calculations, 40 endpoints, 35 errors, 5 roles (WellOwner entity-backed; WaterMaster / EnforcementOfficer / AppealsOfficer / StateRegulator opaque), 28 validation rows, 1 OCC concurrency rule (`account-update-stale-version` on PATCH /water-user-accounts/{id}).
- **§1.8**: 18 instances — exactly 2 per rule, all 9 rules; differentiation honored (dual-variant on account-extraction vs basin-monitoring domains; combinatorial modes (a) tiered penalty and (b) per-report fee rounding; cyclic report machine vs branching appeal machine; depth-3 verify→overdraft cascade vs depth-2 CRITICAL-publish→expiry cascade; state-vs-safety and constraint-vs-fiscal priority pairs; breach-pct vs water-volume boundaries; Report→Well vs Transfer→Snapshot cross-entity gates; half-open adjacency vs aggregate month-cap overlap; water vs money compensating invariants). All formula-derived asserts pre-computed as literals (e.g., penalty 950000/175000 cents, fees 3666+3666=7332 vs naive 7333).
- **§1.9**: 44 entries — 40 non-stub instances across all nine guide sections (entities 6, state_machines 10, calculations 4, validations 12, endpoints 2, errors 1 real + 4 stubs, rbac 3, cross-cutting 2, consistency 1) + 4 `excluded_because:` stubs citing §1.8 instances.
- **Verification**: all 62 instance names unique across both files; every grounds reference resolves; all 35 error codes are triggered by at least one instance; enum values all reachable; final `scaffold_lint.py` verdict — `VERDICT: clean lint` (428 calls scanned, 0 violations; FK reverse-reachability satisfied via filtered lists plus `GET /wells/{id}/monitoring-readings`).

## Step 4: Generate PRD — 2026-08-15T08:58:00.000Z

## Summary

**Output path:** `/home/ubuntu/github/CodingPRD/tasks/task_2029_groundwater_sustainability_well_metering/workspace/PRD.md`
**Line count:** 247 lines

**Section list:**
- §1 Introduction (2 paragraphs: business context + system overview)
- §2 Global Specifications & System-Wide Principles
  - 2.1 User and Role-Based Access Control (5 roles with entity-backed vs opaque identity prose)
  - 2.2 API Response Structure (verbatim fixed block)
  - 2.3 Pagination
  - 2.4 Common Resource Properties (with `MonitoringReading` carve-out)
  - 2.5 The Logical Clock and the Water Year
  - 2.6 Precision, Rounding, and Monetary Representation
  - 2.7 The Official Basin Condition as Derived Posture
  - 2.8 Validation Order and Nested Retrieval
  - 2.9 Optimistic Concurrency Control on Account Updates
- §3 Business Logic & Workflows (8 subsections)
  - 3.1 Onboarding Water Users and Registering Wells
  - 3.2 Metering, the Domestic Exemption, and Well Activation
  - 3.3 Monthly Extraction Reporting and the Revision Loop
  - 3.4 The Transfer Market: Proposal, Acceptance, Settlement
  - 3.5 Monitoring Wells and Basin Condition Snapshots
  - 3.6 Penalties, Appeals, and the Segregation of Duties
  - 3.7 Year-End Close and the Annual State Report
  - 3.8 Account Suspension, Closure, and Effective Allocation
- §4 Endpoint Definitions (intro paragraph + 40-row, 4-column table)
- §5 Error Code Catalogue (35-row, 2-column table)

**Coverage audit — all three hard contracts PASS:**

- **Contract 1 (Field-Name Coverage):** 66 required identifiers (entity fields + endpoint `input` keys + inline response keys `closed_water_year`/`accounts_rolled`/`total_carryover_af`/`current_utc`), 66 present in backticks, 0 missing. **PASS**
- **Contract 2 (Rule Coverage):** 43 spot-checks across all six high-risk categories — validation priority ordering (validation pipeline §2.8), OCC rule (§2.9, with `expected_account_version` + `ERR_STALE_VERSION` + HTTP 412 all named), cross-entity side effects (verify-report cascade, publish-CRITICAL market suspension, close-account cascade), `applies_to` scopes, structured field content (defaults, conditional presence, nullability), and sibling-branch symmetry (`UPHELD`/`OVERTURNED`/`REDUCED` each with full ledger semantics) — plus all 9 calculation formulas with constants embedded (0.80 curtailment, 3000 c/af, 1.00/1.10/1.25 multipliers, 10% tier-1 limit, 10000/25000 tier rates, 10000/50000 flat fees, 25% carryover cap, 5000 af monthly cap, 90-day recency, 50/25 breach thresholds, 120/100 mean thresholds, 30-day appeal window, 72-hour transfer expiry, 16th-of-month late boundary). 43/43 expressed. **PASS**
- **Contract 3 (§3 Path Purity):** 394 backticked tokens scanned in §3, 0 start with `/`, 0 bare HTTP methods, 0 method+path combinations. **PASS**

**Auxiliary checks:**
- All 35 error IDs present in backticks in PRD prose.
- All 25 state-machine state names present in backticked UPPERCASE.
- All 5 role names present with exact spelling.
- All 37 enum values present (the scraper's lone "OFFICIAL" miss was a false positive from a descriptive adjective in the scaffold, not an enum value).
- All 40 endpoint paths present in §4; §4 table has exactly 4 columns; §5 table has exactly 2 columns.
- No leakage from `SCAFFOLD_DIFFICULTY_DESIGN.yaml` or `SCAFFOLD_CORNER_DESIGN.yaml` (those files were never opened, grepped, or referenced).

Zero omissions across entities, state machines, calculations, validations, endpoints, errors, and roles.

## Step 5: Generate Unit Tests — 2026-08-15T09:30:00.000Z

All generation and audits are complete. Final summary:

## Generated output

**`test_helpers/` (9 files)** — `/home/ubuntu/github/CodingPRD/tasks/task_2029_groundwater_sustainability_well_metering/test_helpers/`
- `types.py` — 8 entity TypedDicts + 10 status/role enums; `MonitoringReading` correctly omits `updated_at`/`version` (append-only per PRD §2.4)
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD endpoint (40 endpoints)
- `api_errors.py` — all 35 error IDs with HTTP status map, registered via `set_error_http_status_map`
- `assertions.py` — per-entity `assert_*()` shape checkers (incl. asserting absence of `updated_at`/`version` on readings)
- `factories.py`, `constants.py` (fee rates, tier rates, 0.80 curtailment, 5000-af monthly cap, 25% carryover cap, 72h expiry, 30-day appeal window, fixed clock default)
- `test_users.py` — shared constants for the four opaque roles + `make_well_owner_headers(account_id)` builder for the entity-backed WellOwner (used by all ownership-gated fixtures)
- `fixtures.py` — composite helpers: account/well state progression (metered production path, exemption paths), report submit/verify/dispute/resubmit, transfer propose/accept/settle, `setup_basin_condition(depths, publish=...)` for the reused 4-monitoring-well fixture, assessment/appeal/decide/pay, year close, clock control
- `__init__.py` — barrel export

**`test_suite/` (conftest.py + 11 test files, 75 tests)**
- test_01 accounts/envelope: 2 · test_02 wells: 8 · test_03 extraction reports: 10 · test_04 fees/overdraft: 5 · test_05 appeals: 9 · test_06 transfer market: 15 · test_07 basin condition: 7 · test_08 CRITICAL suspension: 7 · test_09 year close/annual report: 7 · test_10 security/not-found: 3 · test_11 OCC/expiry: 2

## Coverage vs. the design indices

- **Queue A (Difficulty): 18/18 instances emitted, each with exactly 2 tests** (36 tests). Both priority-pair instances were emitted because PRD §2.8 ("earlier failures mask later ones… from-state preconditions… and only then the business-constraint, business-safety, and business-fiscal rules") and §3.4 ("three independent gates evaluated in the order stated here. First… Second… Third…") state the precedence explicitly.
- **Queue B (Corner): 39/40 non-stub instances emitted** (39 tests). The 4 `excluded_because:` stubs were not translated; all 4 `difficulty_instance` pointers verified to resolve.
- **Skipped (1):** `Corner/entities/account_creation_computed_input_ignored` — fails the unique-derivability condition: the PRD lists create-payload shape checks (§2.8) but never states whether client-supplied computed fields are ignored or rejected, so two faithful PRD-only implementers could ship different behavior. No placeholder, no skip marker emitted.

## Verification performed
- All 75 test functions carry **exactly one** `Design:` tag, as the **last** docstring line, and every tag resolves verbatim to a real `name:` in the source YAML (programmatically audited — 0 untagged / 0 dual-tagged / 0 dangling).
- All 114 quoted PRD citations in docstrings appear **verbatim** in `workspace/PRD.md` (whitespace-normalized check, plus literal-grep spot check).
- No `pytest.mark.skip`/`skipif`/`xfail` anywhere; no "scaffold" references in generated code comments/docstrings; all modules import cleanly against the installed framework.

## Step 6: Generate Implementation — 2026-08-15T09:30:00.000Z

Implementation complete and verified. Summary:

## File list
All under `/home/ubuntu/github/CodingPRD/tasks/task_2029_groundwater_sustainability_well_metering/workspace/implementation/`:

- `start.sh` — guarded launcher (executable)
- `requirements.txt` — `flask>=3.0`
- `app.py` — Flask app factory, error handlers (ApiError/404/405/HTTP/500), route registration, `0.0.0.0:$PORT` entry
- `db.py` — in-memory `Store` (per-entity dicts, `closed_years` set, arrival-sequence counter, logical clock defaulting to `2026-08-01T00:00:00Z`)
- `errors.py` — `ApiError` + all 35 catalog error IDs with HTTP statuses
- `response.py` — envelope builders (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`; pagination fields in `meta` for lists)
- `middleware.py` — `X-User-ID`/`X-User-Role` auth, role gating, body parsing, `limit`/`offset` pagination (default 10, min 1, cap 100, offset ≥ 0)
- `serializers.py` — per-entity serializers (Decimal→number, datetimes→ISO 8601 with 3 fractional digits; `MonitoringReading` omits `updated_at`/`version`)
- `services.py` — all 9 calculations (effective allocation with 0.80 CRITICAL curtailment, forward/settled available-water variants, per-report fee with condition multiplier, two-tier overdraft penalty, dual-variant basin evaluation, carryover, monthly transfer cap, late flag, annual aggregates) plus cascades (verify overdraft auto-assessment, transfer expiry sweep, CRITICAL-publish market suspension, account-close cascade)
- `routes/` — `accounts.py`, `wells.py`, `reports.py`, `transfers.py`, `monitoring.py`, `snapshots.py`, `penalties.py`, `annual.py`, `admin.py`

## Coverage
- **Entities: 8/8** — WaterUserAccount, Well, ExtractionReport, TransferOrder, MonitoringReading (append-only: `id`+`created_at` only), BasinConditionSnapshot, PenaltyAssessment, AnnualStateReport.
- **Endpoints: 40/40** — accounts 4, wells 6, extraction-reports 6, transfer-orders 7, monitoring-readings 2 (incl. `/wells/{id}/monitoring-readings`), snapshots 3, penalty-assessments 6, annual-state-reports 4, admin close-water-year 1, logical clock 1.
- **Errors: 35/35** enforced in scaffold priority order (auth → ownership → shape → existence L-to-R → state → business), including `ERR_STALE_VERSION` (412) OCC via `expected_account_version`, segregation-of-duties on appeal decisions, and the settle-time re-check with the order's own reservation removed.

## In-memory state
A module-level `Store` singleton rebuilt on every process boot: eight plain dicts keyed by UUID (insertion order = arrival order for `created_at` tie-breaking), a `closed_years` set gating annual-report generation, a monotonic `_seq` counter for selector/latest-reading tie-breaks, and the logical clock. Acre-feet are `Decimal` quantized to 3dp round-half-up; cents are ints; depths/percentages 2dp. **No seeding of any kind** — a fresh boot returns `total_count: 0` on every list (verified).

## start.sh contract
Confirmed: reads `$PORT` (default 10000), binds `0.0.0.0` via `app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))`, runs in the foreground via `exec python3 app.py`, and guards the dependency install behind `python3 -c "import flask"` so per-test reboots skip `pip install`.

## Verification
Two smoke suites run against fresh boots (58 + 15 checks): CRUD, auth/RBAC/ownership, OCC 412, all state machines incl. the SUBMITTED→DISPUTED→SUBMITTED revision loop, overdraft auto-cascade with tiered penalty math (32 af over → 650000 cents), fee multipliers (1.00/1.25 verified), CRITICAL publish market suspension, clock-sweep expiry (strictly-before `expires_at`), appeal window (+30 days exact), REDUCED/OVERTURNED/UPHELD branches, monthly cap equality boundary (5000 allowed), half-open window adjacency, 90-day recency inclusivity, carryover rollover, and annual-report aggregates — all passing. The only failures encountered during testing were arithmetic errors in my own ad-hoc test expectations, not in the implementation.

## Step 7: Run Tests and Iterate — 2026-08-15T09:38:00.000Z

Clean 8-round parallel sweep achieved: 75/75 passed in every round.

**Summary**

- **Iterations run:** 2 (initial sweep surfaced 1 deterministic failure in all 8 rounds; fix applied; verification sweep fully green).
- **Tests deleted:** none.
- **Fixes applied to `test_helpers/`:** none — the helper itself was correct and exported.
- **Fixes applied to test files:**
  - `/home/ubuntu/github/CodingPRD/tasks/task_2029_groundwater_sustainability_well_metering/test_suite/test_09_year_close_and_annual_report.py` — added the missing import of `setup_account_with_verified_extraction` to the `from test_helpers import (...)` block. `TestCarryover::test_carryover_credit_applies_cap_at_year_close` used this fixture but never imported it, producing `NameError: name 'setup_account_with_verified_extraction' is not defined`. The test's assertions (carryover cap `min(unused, 0.25 × base_allocation_af)`, ledger resets, `current_water_year` advance) trace verbatim to PRD §3.7, so the test stayed; only its import block was wrong (STEP 2 test bug).
- **Fixes applied to `implementation/`:** none — the implementation was already PRD-faithful for every exercised rule.

Final state: 8/8 rounds × 75/75 tests passing under `--isolation per-test-server`.

## Step 8: Finalize PRD — 2026-08-15T09:42:00.000Z

## Summary

**PRD_FINALIZED.md is intentionally identical to PRD.md** — the Step 7 diff reveals no PRD silence and no PRD/implementation mismatch.

### Line counts and delta
- `PRD.md`: 247 lines
- `PRD_FINALIZED.md`: 247 lines
- Delta: 0 lines, 0.0%

### Analysis of the single Step 7 item

The only Step 7 fix was in `test_suite/test_09_year_close_and_annual_report.py`: adding the missing import of `setup_account_with_verified_extraction` to the `from test_helpers import (...)` block. This is a **pure test artifact bug** (a `NameError` from an un-imported fixture) with zero behavioral content:

1. **The helper exists and was correctly exported** — `test_helpers/fixtures.py:313` defines `setup_account_with_verified_extraction`; no `test_helpers/` fix was needed.
2. **The test's assertions trace verbatim to PRD §3.7** — carryover cap `min(unused, 0.25 × base_allocation_af)` with half-up 3-decimal rounding, `credit_balance_af` grant surviving the boundary, `extracted_af_ytd`/`pending_extraction_af`/`transfer_out_af_ytd` resets, `current_water_year` advance, and the `closed_water_year`/`accounts_rolled`/`total_carryover_af` response fields are all already spelled out in §3.7.
3. **The implementation matches PRD §3.7 exactly** — `workspace/implementation/routes/admin.py:15-51` (`close_water_year`) implements precisely that prose: unresolved-report gate (`ERR_CLOSE_YEAR_UNRESOLVED_REPORTS`), ACTIVE/SUSPENDED + matching-year account selection, `unused = max(0, effective_allocation − extracted_af_ytd − transfer_out_af_ytd)` rounded via `round3` (ROUND_HALF_UP, confirmed in `util.py:11-12`), `carry = round3(min(unused, CARRYOVER_CAP_FRACTION × base_allocation_af))` with `CARRYOVER_CAP_FRACTION = Decimal("0.25")` (`services.py:22`), credit grant, ledger resets, year advance, version increment, and the three response fields. The curtailment-aware `effective_allocation` (`services.py:50-52`, 0.80 under CRITICAL / 1.00 otherwise) matches §3.8 and §3.7's closing sentence.

### Changes made
None. No PRD edit was warranted: the diff item is a Python import fix in a test file, which pins no behavioral choice and exposes no divergence between PRD prose and implementation behavior.

### Per-edit pre-edit search log
No edits were committed, so no pre-edit searches were triggered. The verification searches performed covered the full subject surface of the lone Step 7 site: the year-close endpoint (`routes/admin.py`), the carryover constant and `effective_allocation`/`available_water`/`compute_overdraft_af` helpers (`services.py`), rounding primitives (`util.py`), and the fixture definition (`test_helpers/fixtures.py:313`) — all consistent with the existing PRD wording, confirming that leaving the prose verbatim introduces no new mismatch.

## Step 9: Complete PRD — 2026-08-15T09:52:00.000Z

Done. `workspace/PRD_COMPLETED.md` produced.

**Source/line stats:** Source `PRD_FINALIZED.md` (identical to `PRD.md`): 247 lines / 40,700 chars → `PRD_COMPLETED.md`: 248 lines / 43,478 chars (+1 line, +2,778 chars; 17 diff hunks, all in-paragraph inserts except one added bullet in the existing §2.2 bullet list).

**Counts:** 17 ambiguity-pins (inserts), 0 mismatch-revisions. No true contradictions found — every divergence was PRD silence, never counter-specified behavior.

**Changes (one bullet each):**
- §2.2 Error format — insert — ambiguity — pin catch-all handlers: unknown path → `ERR_NOT_FOUND` (404), unsupported method → `ERR_METHOD_NOT_ALLOWED` (405), unexpected failure → `ERR_INTERNAL` (500) — app.py:21-36
- §2.3 Pagination — insert — ambiguity — non-integer/`limit`<1 and non-integer/negative `offset` → `ERR_INVALID_REQUEST`; `limit`>100 silently clamped to 100 — middleware.py:27-50
- §2.5 Logical clock — insert — ambiguity — clock set accepts any parseable ISO 8601 instant (no monotonicity constraint); `current_utc` echoes the supplied `to_iso8601` string verbatim — routes/admin.py:54-64
- §2.6 Precision — insert — ambiguity — quantities serialize on the wire as JSON numbers (trailing zeros may drop) — util.py:80-82, serializers.py
- §2.7 Basin selector — insert — ambiguity — ties beyond `computed_at`/`created_at` break by request-arrival order, most recently created snapshot wins — services.py:38
- §2.9 Optimistic concurrency — insert — ambiguity — stale-version check positioned after account existence, before status-transition/closure rules — routes/accounts.py:101-110
- §3.1 Well registration — insert — ambiguity — `minimum_threshold_ft` accepts any numeric value (no sign/decimal-place constraint) — routes/wells.py:38-40
- §3.2 Meter install — insert — ambiguity — `meter_serial` must be a non-empty string — routes/wells.py:96-98
- §3.2 Activation — insert — ambiguity — account-`ACTIVE` check evaluated before the well's from-state check — routes/wells.py:120-128
- §3.3 Report submission — insert — ambiguity — duplicate-report check evaluated before the `water_year`-match check — routes/reports.py:46-51
- §3.4 Transfer proposal — insert — ambiguity — proposer must own the seller account; `unit_price_cents` must be a non-negative integer; both-`ACTIVE` check evaluated before the self-transfer rule — routes/transfers.py:26-58
- §3.5 Snapshot input set — insert — ambiguity — per-well latest-reading ties beyond `created_at` break by arrival order; recency window is the inclusive [clock−90d, clock] (exactly 90 days qualifies, after-clock excluded) — services.py:118-120
- §3.6 Manual assessment — insert — ambiguity — `water_year` is any integer (not tied to account's `current_water_year`); target account status unconstrained (may assess `ACTIVE`/`SUSPENDED`/`CLOSED`) — routes/penalties.py:31-48
- §3.6 Assessment fields — insert — ambiguity — `overdraft_af` null for non-`OVERDRAFT`; `reduced_amount_cents`/`paid_amount_cents`/`decided_by` null until set — services.py:225-241
- §3.7 Year close — insert — ambiguity — re-closing an already-closed year is permitted, rolling whatever accounts are then stamped with that year — routes/admin.py:15-51
- §3.8 Account update — insert — ambiguity — new `base_allocation_af` must satisfy the onboarding rule (>0, ≤3dp); explicit nulls treated as absent; a request supplying neither field is a 200 no-op with no version bump; any transition outside the four allowed (including same→same) → `ERR_ACCOUNT_NOT_ACTIVE` — routes/accounts.py:91-127
- §4 Endpoint preamble — insert — ambiguity — list filters are exact-match (unmatched values yield an empty page); non-integer `water_year` filter → `ERR_INVALID_REQUEST` — middleware.py:68-76, routes/reports.py:81, routes/annual.py:61

**Cross-checked but already pinned (no change):** all state machines, fee/tier/multiplier formulas, carryover math, three proposal gates and their order, settle preconditions and their order, overdraft-crossing cascade, CRITICAL publish suspension, validation-pipeline tiers (§2.8 already covers state-before-type ordering on install-meter/report/reading creation), error catalogue §5 (all 36 codes match `errors.py` statuses exactly), envelope shape, and version-increment cascades.
