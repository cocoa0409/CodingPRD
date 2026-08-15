# Worklog — task_1820_compressed_air_audit_service_contract

## Step 1: Create Task Directory — 2026-08-14T18:58:00.000Z

Directory `tasks/task_1820_compressed_air_audit_service_contract/` and `workspace/` pre-created by the invoking command (Step 1 done out-of-band per command args).

## Step 2: Generate Scaffold — 2026-08-14T19:55:00.000Z

All checks pass. Final summary of the generated scaffold for task 1820 (Compressed-Air Audit & Service Contract).

### Files written (all three, verified parsing and lint-clean)

- `SCAFFOLD.yaml` — §1.0–§1.7 only (no design keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` — single top key `scaffold_corner_design`

### Metrics

- **Entities: 14** — Facility, Compressor, DemandProfile (self-referential supersede chain), LeakSurvey, LeakTag, MaintenanceSchedule, RetrofitProject, SavingsCase, ServiceContract, ServiceTicket, RentalAsset, RentalReservation, GuaranteeCertificate, ServiceCredit (flat topology, FKs in bodies, every FK has a reverse-reachability GET)
- **Endpoints: 89** (exceeds the 32 guideline deliberately — posture gating + dual-variant measurement pipeline + rental selector demand it; all 89 are reachable and lint-referenced)
- **Error codes: 40** (each referenced by a validation/transition and exercised by at least one §1.8/§1.9 instance)
- **State machines: 14** — cycles (Compressor IN_SERVICE↔DOWN, ServiceContract ACTIVE↔SUSPENDED, RentalAsset AVAILABLE↔ON_RENT), independent dual dimensions (SavingsCase savings×rebate, GuaranteeCertificate settlement×dispute with a recompute loop on upheld disputes), compensation (authorize→wont-fix budget release)
- **Calculation variants: 3 dual-variant pairs across different entity domains** (deemed 522800 vs measured 486667 kWh on SavingsCase; quoted 350000¢ vs actual 140000¢ on RentalReservation; provisional 1968400¢ vs final 1860001¢ rebate) plus a pinned per-leak-round-then-sum order (2374 vs rejected 2373)
- **§1.8 instances: 21** (≥2 per rule): dual_variant_calc 2, combinatorial_formula 3 (modes a/b/c: tiered-rebate-min-caps, per-leak rounding, gross-fee SLA credit ordering), non_linear_state_machine 3, transitive_cascade 3 (run-hours→schedule→posture→certificate gate depth-4; ticket→credit→contract auto-suspend; decommission→project-cancel→retrofit_stale), priority_pair_validation_conflict 2 (state×fiscal, referential×temporal), boundary_precision_check 2 (run-hours `>=` at exactly 6000; SLA `<=` at exact deadline second), cross_entity_state_dependency 2, resource_temporal_overlap 2 (rental turnaround-buffer vs plain closed-closed profile windows), compensating_invariant 2 (rental escrow dollars; credit partition identity accrued == applied+expired+outstanding)
- **§1.9 instances: 59** (51 active + 8 `excluded_because` stubs) across all nine guide sections, including 2 OCC stale-version tests, selector-policy ranking/tie-break/empty-pool, rebase version-pinning recovery, segregation-of-duties ×2, RBAC denials, ownership enforcement, pagination envelope
- All formula-derived asserts are pre-computed literals (verified by executing the formulas in Python); logical clock default pinned at `2026-08-01T00:00:00Z`

**Lint verdict (verbatim):** `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (89 endpoints, 14 entities, 21 §1.8 + 51 §1.9 instances, 842 calls scanned). Additional audits passed: placeholder closure, cross-file name uniqueness, grounds resolvability, forbidden-vocabulary scan, enum closure, terminal-state lockdown, OCC hard constraints, trigger↔side-effect bidirectional match.

## Step 3: Copy Shared Files — 2026-08-14T19:56:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1820_compressed_air_audit_service_contract/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-14T20:10:00.000Z

All checks pass. The flagged "fuzzy word" hits are false positives — "around the clock" (idiom) and matches inside the domain noun "turnaround" — no approximating quantifiers exist anywhere. The document ends at §5 with no audit footer.

### Summary

**Output:** `workspace/PRD.md` — 387 lines.

**Section list:**
- §1 Introduction (2 paragraphs)
- §2 Global Specifications: 2.1 User and Role-Based Access Control · 2.2 API Response Structure (fixed block, byte-verbatim) · 2.3 Pagination · 2.4 Common Resource Properties · 2.5 The Logical Clock · 2.6 Facility Posture and the Settlement Gate · 2.7 Optimistic Concurrency Control on the Facility Version · 2.8 Measurement Units, Rounding, and Monetary Precision · 2.9 Validation Order and Request Rejection
- §3 Business Logic: 3.1 Facility Onboarding and Lifecycle · 3.2 Compressor Registry, Run-Hours, and Dryer/Filter Maintenance · 3.3 Demand Profiles and Baseline Locking · 3.4 Leak Surveys and the Repair Pipeline · 3.5 Retrofit Projects and Compressor Sequencing · 3.6 Savings Cases, Measurement, and Utility Rebates · 3.7 Service Contracts, Response SLAs, and Service Credits · 3.8 Rental Fleet Operations and Outage Substitution · 3.9 Guarantee Certificates, Settlement, and Measurement Disputes
- §4 Endpoint Definitions (89 rows, 4 columns) · §5 Error Code Catalogue (40 rows, 2 columns)

**Hard contract reports:**

```
Field coverage check:
- entities[].fields + common fields: 107 required, 107 present, 0 missing
- endpoints[].request_body / clock output fields: 10 required, 10 present, 0 missing
- endpoints[].query_params (incl. min_rated_cfm, limit, offset): 2 unique-to-query required, 2 present, 0 missing
  (combined set: 119 required, 119 present, 0 missing)
Status: PASS

Rule coverage check:
- validations[] with priority: 30 checked, 30 expressed (10-tier global order in §2.9; per-endpoint in-tier orders pinned in §3, incl. ERR_BASELINE_SUPERSEDED winning over ERR_RETROFIT_STALE), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (lock + activate writes; expected_facility_version + ERR_STALE_VERSION/412 named; no race framing), 0 missing
- state_machines[].transitions: 64 checked, 64 fully expressed (all from/to states, preconditions paired with error ids, side effects incl. decommission/supersede/breach cascades), 0 missing
- calculations[]: 13 checked, 13 fully expressed in reconstruction-safe prose (pinned rounding orders, inclusive boundaries, constants embedded; deemed-vs-measured / quoted-vs-actual / provisional-vs-final variants all stated), 0 missing
- validations[] conditions: 30 checked, 30 matchable to error ids in §2/§3 prose (40/40 error ids present), 0 missing
- endpoints[].side_effects / applies_to: 89 endpoints checked; multi-endpoint scopes (e.g. ERR_FACILITY_NOT_ACTIVE ×6, ERR_FACILITY_MISMATCH ×6) enumerated, 0 missing
- entities[].fields[] structured content: 107 checked — types, defaults, null-until semantics, snapshots, immutable tier, gross-fee credit base all reconstructible, 0 missing
- sibling-branch symmetry: 8 groups checked (settle branches, dispute outcomes, rebate decision outcomes, wont-fix sources, terminate sources, decommission sources, offboard sources, ticket-cancel sources) — equal prose density, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 687
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional verifications: §2.2 matches the canonical block byte-for-byte (including `req_RANDOMALPHANUM123456`, `2025-05-24T10:30:00.123Z`, empty `"data": { }`); all 68 state/enum values from the scaffold appear as exact UPPERCASE strings; §4 roles match the scaffold's per-endpoint role lists exactly; §5's 40 rows match scaffold error ids and HTTP statuses; no pseudocode operators, fuzzy quantifiers, or race-framing anywhere; the withheld difficulty/corner design files and sibling tasks were never opened.

## Step 5: Generate Unit Tests — 2026-08-14T20:50:00.000Z

All done. Final summary:

### Task 1820 test generation — complete

**Test counts (93 total, all collecting cleanly under pytest):**
- **Queue A (Difficulty): 42 tests** — all 21 instances covered with exactly 2 tests each
- **Queue B (Corner): 51 tests** — all 51 non-stub instances covered with 1 test each
- Per file: test_01 facilities/RBAC/envelope (10), test_02 compressors/maintenance (9), test_03 demand profiles/OCC/rebase (8), test_04 leak surveys/repairs/SoD (10), test_05 retrofits/savings/rebates (17), test_06 contracts/tickets/credits (12), test_07 rentals (19), test_08 guarantee certificates (8)

**Skipped instances:** none. The 8 corner `errors:`-section stubs (`excluded_because:`) were not translated per spec; all their `difficulty_instance` cross-references verified to resolve.

**Helper files written** (`test_helpers/`, ~1400 LOC): `types.py` (14 TypedDicts + 21 enums), `api_client.py` (one method per endpoint), `api_errors.py` (38 error IDs registered with the framework status map), `assertions.py` (per-entity validators + credit-partition invariant + strict 3-fractional-digit timestamp check), `factories.py`, `constants.py` (all PRD §3 numeric constants), `test_users.py` (shared constants + per-instance builders; FacilityManager builder mandatory for ownership-gated calls), `fixtures.py` (composite pipelines: `setup_savings_pipeline`, `setup_certificate_pipeline`, `setup_contract_with_breaches`, `setup_rental_scenario`, OCC-aware lock/activate helpers, logical-clock utilities), `__init__.py` barrel.

**Stage 1/2 audit results — all PASS:**
- pyflakes clean; `pytest --collect-only` collects 93/93 with zero errors
- Coverage audit: every difficulty instance ≥2 tests, every non-stub corner instance ≥1, zero untagged/dual-tagged/orphaned tests; every docstring ends with exactly one verbatim `Design:` line
- Citation audit: 137 PRD citations, all verified as verbatim substrings of PRD.md

**Two adjudications worth flagging:**
1. `corner_facility_create_defaults_and_system_fields` and `corner_immediate_read_after_write_consistency` assert `version == 1` on creation. PRD §2.4 says version "increments with every mutation" but never pins the initial value — fails the two-reader test. I relaxed those two sub-assertions only (type/presence check; create-vs-reread version equality for the consistency test), keeping both instances' core claims.
2. Difficulty instance `certificate_dispute_recompute_loop` has an internally inconsistent recipe: its asserted literals (guaranteed 470520, deadband 9410, shortfall 41110, payout 493320) require deemed = 522800 (i.e., the 3 canonical closed leaks), but its `setup_api_calls` omit the leak pipeline. I supplied the canonical 3-leak setup (12.5/8.0/1.5 CFM, all VERIFIED_CLOSED) so every asserted literal holds; without it the recipe would produce guaranteed 446760 and contradict its own asserts.

## Step 6: Generate Implementation — 2026-08-14T20:40:00.000Z

Done. The implementation is complete and verified.

### Summary

**Task**: `task_1820_compressed_air_audit_service_contract` — full Python + Flask implementation in `workspace/implementation/`.

**File list** (16 source files, ~3,100 LOC):
- `start.sh` — foreground launcher: `cd`s to its own dir, guards dependency install behind `python3 -c "import flask"` (no-op once Flask present, so per-test reboots never re-run pip), then `exec python3 app.py`
- `requirements.txt` — `flask>=3.0,<4`
- `app.py` — entry point, ApiError/404/405/500 handlers, global request lock, blueprint registration; `app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))`
- `store.py` — 14 module-level dicts (all empty at boot, zero seeding), logical clock, monotonic ms-precision wall timestamps, `new_resource`/`touch` (version+updated_at) helpers
- `errors.py` — full error catalog with exact scaffold IDs/statuses
- `envelope.py` — `meta`/`response_type`/`data` envelope, error body, list pagination fields
- `auth.py` — X-User-ID/X-User-Role validation, role gating, FacilityManager ownership (direct + parent-chain: leak tag via survey, credit via contract)
- `domain.py` — all calculations (baseline annualization, per-tag leak kWh with pinned per-tag rounding, deemed = leak rollup + sequencing with 20-psi cap, tiered utility rebate with cost/program caps, SLA deadline/credit, rental quote vs actual billing with 3-day floor and 28-day 85% discount, maintenance delinquency, facility posture, guarantee settlement), recompute chains, selector, decommission cascade
- `routes/` — 13 blueprints: clock, facilities, compressors, demand_profiles, leaks, maintenance, retrofits, savings, contracts, tickets, rentals, certificates, credits

**Endpoint count**: 89 routes registered — every row of the scaffold §1.5 table (Flask's built-in `/static` route explicitly disabled).

**Logical clock**: module-level datetime in `store.py`, initialized to exactly `2026-08-01T00:00:00Z` at process start, never wall-clock. `POST /_clock/set_current_utc` (DealerAdmin-only) sets it from `to_iso8601` (normalized to UTC, truncated to seconds) and returns `{current_utc}`. It stamps `reported_at`/`first_response_at`/`accrued_at` (second-granularity ISO), `accepted_date`, and drives contract-expiry (strictly after `end_date`) and credit-expiry (inclusive `>= expires_at`) checks. `created_at`/`updated_at`/`meta` timestamps use monotonic-guarded wall clock at 3-fractional-digit precision, per PRD §2.4/§2.5's explicit separation.

**Boot confirmation**: `bash start.sh` from `./implementation/` with `PORT=18301` answered HTTP 200 on both 127.0.0.1 and the external interface within ~2.5s, with all 14 collections empty (`total_count: 0`) and the clock at the spec default; the pip guard logged no install.

**Verification**: 189 assertions across 7 end-to-end smoke suites passed on fresh boots — auth/role/ownership tiers, envelope shapes, pagination, OCC (412 on profile lock + contract activate), supersede cascades with `baseline_stale`, decommission cascade with `retrofit_stale`, model-gate precedence (`ERR_BASELINE_SUPERSEDED` over `ERR_RETROFIT_STALE`), rebase semantics, SoD (survey verify, close-measurement), pinned rounding example (0.85+1.15 CFM @ 5933 h → 1009+1365 = 2374), rebate provisional-vs-final (deemed vs measured), SLA inclusive deadline, 3-breach auto-suspend + waived termination fee, credit apply/expire identity, rental selector/buffer adjacency (exactly +2 days legal), escrow compensating release, guarantee settle/dispute UPHELD/OVERRULED/pay freeze, and posture-gated settlement with `settlement_blocked` refresh (PAID certificates untouched).

## Step 7: Test/fix iteration loop — 2026-08-14T21:00:00.000Z

**Sweep 1 (8 parallel rounds)**: 91/93 in every round; union of failures = 2 deterministic tests (8/8 rounds each). Phantom "FAILED" progress lines in the interleaved stdout (test_record_service_reading_bounds et al.) were pipe-interleaving artifacts — the per-round summary sections and results JSONs confirmed only the 2 real failures.

**Diagnoses (both test bugs, PRD-faithful implementation confirmed by live repro):**
1. `test_02...::test_duplicate_schedule_component_rejected` — first `validate_success(api.create_maintenance_schedule(...))` omitted the expected-status argument, defaulting to 200; PRD §4 ("Operations that create a new resource return `201 Created`") and the second call in the same test both require 201. Fixed by passing `201`.
2. `test_07...::test_rental_date_range_invalid` — the bad-date create call named an explicit asset that was ON_RENT. PRD §3.8 pins the within-temporal-tier order (explicit-asset `ERR_RENTAL_ASSET_UNAVAILABLE` gates BEFORE the `end_date < start_date` check), so the request could never reach the date-range error; the implementation correctly returned `ERR_RENTAL_ASSET_UNAVAILABLE`. Fixed by dropping `rental_asset_id` from that one call so the date-range rule is the only violation (date-range check precedes the selector per the same §3.8 sentence order). Verified live: server answers `ERR_RENTAL_DATE_RANGE_INVALID`/422.

No tests deleted; no implementation changes.

**Sweep 2 (8 parallel rounds, after the two test fixes): all 8 rounds 93/93 — CLEAN.** Loop exit condition met after 2 iterations. No test deletions; no implementation changes were required.

## Step 8: Finalize PRD — 2026-08-14T21:05:00.000Z

Verification complete. Both Step 7 items were pure test bugs against a PRD-faithful implementation, and the PRD already uniquely pins both behaviors. `PRD_FINALIZED.md` is a byte-identical copy of `PRD.md` — zero edits is the correct output.

### Summary

**File**: `workspace/PRD_FINALIZED.md`

**Line counts / delta**: PRD.md = 387 lines; PRD_FINALIZED.md = 387 lines; diff = IDENTICAL; 0.0% delta. **Zero edits made.**

#### Changes
- None. (No insert, no revise — see per-item verification log below.)

#### Per-item verification log (zero-edit justification)

**Item 1 — `test_02_compressors_and_maintenance.py::test_duplicate_schedule_component_rejected` (create returns 201, not the helper's default 200)**
- (a) Subject: HTTP status of `POST /maintenance-schedules` create, and the duplicate-component rejection.
- (b) Impl paths enumerated and read:
  - `workspace/implementation/routes/maintenance.py:35-72` — create returns `ok_object(public(sched), 201)` (line 72); duplicate ACTIVE (facility, component) raises `conflict(ERR_DUPLICATE_SCHEDULE_COMPONENT)` = 409 (line 55).
  - `workspace/implementation/envelope.py:17-20` — `ok_object(data, code=200)` passes `code` straight through as the HTTP status, so the explicit 201 is honored.
  - Global audit: all 13 resource-creating POSTs across `routes/*.py` return 201 (facilities.py:53, compressors.py:59, demand_profiles.py:83, leaks.py:74 and :131, maintenance.py:72, retrofits.py:70, savings.py:95, contracts.py:81, tickets.py:100, rentals.py:84 and :230, certificates.py:91); every other POST is a state transition returning 200 — PRD §4's blanket sentence is true everywhere in the impl, not just at the Step 7 site.
  - Helper: `validate_success(response, expected_status=200)` in `prd_bench_local_runner.testing` — the pre-fix test omitted the argument; Step 7's fix passing `201` is test-side only.
- (c) PRD quote that already pins it — §4 (line 248): "Operations that create a new resource return `201 Created`; operations that modify an existing resource — including every state-transition action — return `200 OK`", plus §3.2 (line 150) and §5 (line 363) pinning `ERR_DUPLICATE_SCHEDULE_COMPONENT` at 409. No silence, no mismatch → no edit.

**Item 2 — `test_07_rentals.py::test_rental_date_range_invalid` (reservation-creation gate ordering)**
- (a) Subject: within-temporal-tier ordering in `POST /rental-reservations` — explicit-asset availability/overlap gate vs. the `end_date < start_date` check vs. the selector's empty pool.
- (b) Impl paths enumerated and read:
  - `workspace/implementation/routes/rentals.py:142-207` — `create_reservation` runs, in order: headers/role (144), schema (146-154), facility existence (156-158), ownership (159), state gates (162-174: `ERR_FACILITY_NOT_ACTIVE`, `ERR_NO_ACTIVE_CONTRACT`/`ERR_CONTRACT_SUSPENDED`, `ERR_COMPRESSOR_NOT_DOWN`), referential (177-178: `ERR_FACILITY_MISMATCH`), explicit-asset gates (182-194: exists+`AVAILABLE`+sized → `ERR_RENTAL_ASSET_UNAVAILABLE`; buffered overlap → same error), date range (196-197: `ERR_RENTAL_DATE_RANGE_INVALID`/422), selector (200-203: `ERR_NO_RENTAL_ASSET_AVAILABLE`), fiscal (206-207: `ERR_CONTRACT_TIER_INELIGIBLE`). Matches the PRD sentence order exactly; with an explicit ON_RENT asset named, `ERR_RENTAL_ASSET_UNAVAILABLE` fires before the date-range check, as Step 7 observed live.
  - `rentals.py:270-297` — the return path's own `actual_return_date < start_date` check (line 279-280), the second `ERR_RENTAL_DATE_RANGE_INVALID` site covered by the same test; unaffected by the create-path ordering.
- (c) PRD quotes that already pin it — §3.8 (line 222): "then the temporal tier — the asset must be free of buffered overlap and, when explicitly named, must itself be `AVAILABLE` with `rated_cfm` at least the down unit's `rated_cfm` (`ERR_RENTAL_ASSET_UNAVAILABLE` on either count) — and `end_date` must not precede `start_date` (`ERR_RENTAL_DATE_RANGE_INVALID`, HTTP 422); then, when no asset was named and the selector finds nothing, `ERR_NO_RENTAL_ASSET_AVAILABLE`"; independently reinforced by §2.9 (lines 124-125): tier 8 lists "rental overlap with its turnaround buffer, explicit rental-asset choice gates, rental date ranges" and tier 9 contains "the rental selector's empty pool". Both orderings (explicit-asset before date-range; date-range before selector) are uniquely pinned. No silence, no mismatch → no edit.

A fresh implementer reading `PRD_FINALIZED.md` (= `PRD.md`) alone is already forced to the implementation's exact behavior at both sites.

## Step 9: Complete PRD — 2026-08-14T21:15:00.000Z

All edits applied cleanly. Final verification is complete — the diff shows exactly the intended hunks and nothing else.

### Summary

**Files**
- Source: `workspace/PRD_FINALIZED.md` (387 lines, 66,358 chars)
- Produced: `workspace/PRD_COMPLETED.md` (389 lines, 69,443 chars; char-delta +3,085)

**Counts:** 15 ambiguity-pins, 1 mismatch-revision (16 changes total; all in-paragraph inserts/revisions, no new sections).

**Changes**
- §2.1 — insert — ambiguity — pinned that ownership checks apply only to single-resource reads and writes; list reads are not ownership-scoped, and the unowned RentalAsset fleet is never ownership-checked — `implementation/auth.py:54-65`, list handlers in `implementation/routes/*.py`
- §2.3 — revise — ambiguity — pinned `limit` clamped to 1..100 and negative `offset` clamped to 0 (not rejected), non-integer `limit`/`offset` → `ERR_INVALID_REQUEST`, and `has_more` = `offset + returned < total_count` — `implementation/util.py:155-180`, `implementation/envelope.py:22-28`
- §2.4 — insert — ambiguity — pinned `version` starts at 1 at creation with `created_at == updated_at` — `implementation/store.py:80-83`
- §2.5 — revise — ambiguity — pinned clock-set accepts any ISO 8601 datetime (offsets honored, naive read as UTC), normalized to UTC whole seconds, settable to any instant forward or backward — `implementation/routes/clock.py:14-23`, `implementation/util.py:36-51`, `implementation/store.py:41-44`
- §2.8 — insert — ambiguity — pinned that whole-unit quantities (kW/CFM ratings, run-hours, `interval_hours`, `measured_kwh`, `corrected_measured_kwh`, pressures, `term_months`, `expected_facility_version`, all cents fields) are integers, non-integer → `ERR_INVALID_REQUEST`; likewise non-string ids, non-boolean flags, non-object JSON bodies — `implementation/util.py:63-152`
- §2.9 tier 4 — insert — ambiguity — added `interval_hours > 0`, leak-tag `cfm_loss > 0`, `repair_quote_cents >= 0` to the enumerated domain input rules — `implementation/routes/maintenance.py:42-45`, `implementation/routes/leaks.py:108-111`
- §2.9 tier 4 — insert — ambiguity — pinned that a body-carried `facility_id` that does not resolve yields `ERR_NOT_FOUND` (404) as the closing act of the schema tier, ahead of later tiers — e.g. `implementation/routes/compressors.py:35-37`, `implementation/routes/tickets.py:60-62`
- §3.2 — insert — ambiguity — pinned run-hours logging is not state-gated (accepted even for `DECOMMISSIONED` units) and an equal reading is accepted without mutating the compressor — `implementation/routes/compressors.py:85-97`
- §3.2 — insert — ambiguity — pinned that mark-down under an `OFFBOARDED` facility is rejected with `ERR_INVALID_STATE_TRANSITION` — `implementation/routes/compressors.py:106-108`
- §3.6 — insert — ambiguity — pinned the rebate formula applies to the savings figure as-is, so a negative (measured) input yields a negative rebate, reported as-is — `implementation/domain.py:157-163`
- §3.7 — revise — **mismatch** — `end_date` is "same day-of-month `term_months` months after `start_date`" but impl clamps to the last day of the target month when that day-of-month does not exist; PRD now states the clamping rule — `implementation/util.py:54-60`
- §3.7 — insert — ambiguity — pinned "latest non-terminal contract" = the most recently created contract not yet `SUPERSEDED`/`EXPIRED`/`TERMINATED` — `implementation/domain.py:113-122`
- §3.8 — insert — ambiguity — pinned non-integer `min_rated_cfm` filter → `ERR_INVALID_REQUEST` — `implementation/routes/rentals.py:95-100`
- §3.8 — insert — ambiguity — pinned that entering maintenance clears any `next_available_date` the asset carried — `implementation/routes/rentals.py:128-129`
- §3.8 — insert — ambiguity — pinned that delivery cascades the asset to `ON_RENT` and clears its `next_available_date` — `implementation/routes/rentals.py:262-266`
- §3.9 — revise — ambiguity — certificate-creation gate order now includes the savings-case state gate (case must exist with `savings_status` `MODELED` or `MEASURED`, else `ERR_INVALID_STATE_TRANSITION`) between contract presence and cross-facility integrity — `implementation/routes/certificates.py:50-66`
- §3.9 — insert — ambiguity — pinned the settle gate "no dispute open" rejects with `ERR_DISPUTE_OPEN_PAYOUT_FROZEN` — `implementation/routes/certificates.py:129-130`

Everything else in the implementation (all 60+ endpoints, role assignments, state machines, gate orderings, cascade effects, formulas with pinned rounding order, error catalogue and HTTP statuses, envelope shape, filter sets) was verified against the PRD and already uniquely pinned, so no further changes were made.
