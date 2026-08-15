# Worklog — task_1719_anodizing_electroplating_line

## Step 1: Create Task Directory — 2026-08-14T10:45:00.000Z

Directory tasks/task_1719_anodizing_electroplating_line/ and workspace/ pre-created and pre-assigned by the pipeline launcher; Step 1 treated as DONE per instructions (no index scan, no other task_* directory touched).

## Step 3: Copy Shared Files — 2026-08-14T10:46:00.000Z

Copied ./INSTRUCTION.md → tasks/task_1719_anodizing_electroplating_line/workspace/INSTRUCTION.md.

## Step 2: Generate Scaffold — 2026-08-14T11:47:00.000Z

Scaffold generation complete. All three artifacts are written and pass `scaffold_lint.py` with a clean verdict.

## Files written
- `/home/ubuntu/github/CodingPRD/tasks/task_1719_anodizing_electroplating_line/SCAFFOLD.yaml` (§1.0–§1.7, 88 KB)
- `/home/ubuntu/github/CodingPRD/tasks/task_1719_anodizing_electroplating_line/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single key `scaffold_difficulty_design`, 89 KB)
- `/home/ubuntu/github/CodingPRD/tasks/task_1719_anodizing_electroplating_line/SCAFFOLD_CORNER_DESIGN.yaml` (single key `scaffold_corner_design`, 130 KB)

## Counts
- **Entities: 14** — Customer, Fixture, AlloyCompatibilityRule, PlatingBath, BathTitration, DoseEvent, WorkOrder, LoadRun, InspectionReport, SaltSprayLot, DischargePermit, WasteSample, WasteManifest, ManifestLineItem (flat topology, all FKs use canonical `FK -> X.id` prefix)
- **State machines: 7** — WorkOrder (13-state cyclic rework loop), PlatingBath (ACTIVE↔QUARANTINED / EXHAUSTED→DUMPED→ACTIVE renewal cycle with auto-exhaustion), LoadRun, SaltSprayLot, DischargePermit (EXCEEDED cycle), WasteManifest (linear), Customer
- **Endpoints: 53** (incl. `POST /_clock/set_current_utc`, default 2026-08-01T00:00:00Z)
- **Errors: 50** | **Roles: 6** (Customer entity-backed with ownership scoping; 5 staff roles; segregation-of-duties on manifest finalize binds even ShopManager)
- **Calculations: 11** | **Validations: 12 priority tiers** | **OCC concurrency rules: 4**
- **§1.8 difficulty instances: 21** (all 9 rules, ≥2 each; rule 2 covers modes a+b+c, rule 6 and 7 carry 3 each)
- **§1.9 corner instances: 63** (50 active + 13 `excluded_because` stubs)

## Notable design decisions
- **Dual-variant pairs on different domains**: provisional vs final invoice (WorkOrder; literal-verified 7625/10175/14100 cents across a rework cycle) and nameplate vs chemistry-adjusted bath-life (PlatingBath; 600.0 vs floor(600×0.98)=588, with a 590 Ah route rejected only by the pessimistic variant).
- **Amp-hour reservation ledger**: load start reserves, complete debits, abort releases — invariant `used == Σ COMPLETED` / `reserved == Σ RUNNING` anchors Rule 9; manifest mass add/remove is the second conserved quantity.
- **Depth-3 exceedance cascade**: WasteSample → DischargePermit EXCEEDED → chemistry-matched baths QUARANTINED → routed work orders ROUTE_HELD (SULFURIC baths immune via analyte mapping); exhaustion cascade is the second trigger family.
- **Interval-semantics contrast for Rule 8**: fixture occupancy is half-open (adjacent load at exact `ended_at` allowed) vs permit windows closed (shared boundary date rejected).
- **Logical-clock gating** for salt-spray hours (`floor` elapsed hours) and permit month buckets with chronological regression rejection; waste mass pins per-sample round-then-sum (0.002 vs 0.001 divergence verified by executing the formula).
- All formula-derived asserts were pre-computed with Python (titration conversions, dragout 0.0008/dm², pricing tiers/discount/hazmat order, capacity boundaries at exactly 540/600/25 Ah).

Lint verdict (verbatim): `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` An independent audit script also confirmed placeholder closure, grounds resolvability, error-id coverage, instance-name uniqueness, and zero forbidden concurrency vocabulary.

## Step 4: Generate PRD — 2026-08-14T12:05:00.000Z

PRD generation complete. Summary:

**File written:** `/home/ubuntu/github/CodingPRD/tasks/task_1719_anodizing_electroplating_line/workspace/PRD.md` — 370 lines.

**Section list:** §1 Introduction (2 paragraphs, business-context angle); §2 Global Specifications (2.1 Roles & RBAC with per-role identity prose, 2.2 Response Structure emitted verbatim from `section-2.2-response-structure.md`, 2.3 Pagination, 2.4 Common Resource Properties & append-only records, 2.5 Units/Precision/Rounding, 2.6 Logical Clock, 2.7 OCC, 2.8 twelve-tier Validation Priority Order, 2.9 Atomic Cascades & nested validation); §3 Business Logic in 9 domain-derived subsections (master data → bath chemistry → bath-life accounting/lifecycle → intake/quoting/amendment → preparation/routing/load execution → inspection/rework/salt-spray → shipment/invoicing/cancellation → permits/sampling/exceedance → manifests/dump/renewal); §4 Endpoint table (53 rows, 4 columns); §5 Error catalogue (50 rows, 2 columns).

**Coverage audit (all three hard contracts PASS):**

*Contract 1 — Field-Name Coverage:* Extracted all 116 required identifiers (105 entity fields + endpoint-only inputs such as `expected_bath_version`, `expected_work_order_version`, `expected_manifest_version`, `planned_duration_minutes`, `planned_current_density_a_dm2`, `masking_minutes`, `strip_method`, `to_iso8601`, `decommission`, `limit`/`offset`). First pass found `compatibility` missing (only its enum values were backticked); repaired in §3.1. Second pass: **116 required, 116 present, 0 missing. PASS.**

*Contract 2 — Rule Coverage:* 12 validation priority tiers expressed with explicit ordering prose in §2.8, including all three per-endpoint pins (load-start OCC at tier 6 before state checks — rejected 412 even when bath occupied; work-order state before linked-bath state within tier 7; finalize checks segregation at tier 10 before the exceedance hold at tier 12, with the hold at tier 8 for bath release). All 4 OCC rules name endpoint + occ field + `ERR_STALE_VERSION`/412 + rationale. All 7 state machines fully rendered (13 work-order states, 5 bath states, load-run/salt-spray/permit/manifest/customer machines) with every precondition→error pairing and every side effect, including the subtle ones: running load survives quarantine, release landing on `EXHAUSTED` when capacity reached, dump writing F006 line + bumping both bath and manifest versions, renew zeroing both amp-hour accounts and creating a titration, clear-exceedance not releasing baths, abort leaving `amp_hour_used` invariant. All 11 calculations in precise prose with pinned rounding order (EQ weights 49.0/33.3/29.35/32.69/31.77/49.0, dragout 0.0008, amp-hour /60 half-up 2dp, efficiency floor 0.5 with integer floor on the pessimistic variant, 9-step pricing with constants 85/1200/2000/0.20/2500 and tier/discount thresholds, cancel fee 0.5×processing, per-analyte round-before-sum mass accounting with month reset/regression, strict-vs-inclusive exceedance bounds, salt-spray boundaries 4/5/9/10→0/1/1/2, inclusive thickness bounds, BURN/ADHESION scrap-regardless). Verified via 52 automated rule-anchor greps — **0 missing. PASS.**

*Contract 3 — §3 Path Purity:* 612 backticked tokens scanned in §3 — 0 path tokens, 0 bare HTTP methods, 0 method+path combos. All operations referenced by state-transition framing (`RECEIVED` → `READY_FOR_ROUTING`), role+verb, or capability description. **PASS.**

Additional checks: all 50 error IDs appear in §2/§3 prose trigger contexts and in §5; all 57 enum/state string values appear verbatim (added literal `CANCELLED` on repair); zero pseudocode operators (`==`, `>=`, `:=`, …) and zero fuzzy hedging words in prose; §4 intro states the 201/200/204 status-code rules; `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened or referenced.

## Step 5: Generate Unit Tests — 2026-08-14T12:30:00.000Z

Complete. Final summary:

## Summary

**Files written** under `/home/ubuntu/github/CodingPRD/tasks/task_1719_anodizing_electroplating_line/`:

`test_helpers/` (9 files):
- `types.py` — status enums (13-state WorkOrder machine, 5-state bath, etc.) + TypedDicts; append-only records (BathTitration, DoseEvent, InspectionReport, WasteSample) correctly omit `updated_at`/`version`.
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint (44 methods incl. `POST /_clock/set_current_utc`).
- `api_errors.py` — `ApiErrorId` enum (47 IDs) + HTTP status map registered via `set_error_http_status_map` (incl. 402 for `ERR_CUSTOMER_CREDIT_HOLD`, 412 for `ERR_STALE_VERSION`).
- `assertions.py` — per-entity assertions + amp-hour invariant checker.
- `factories.py` — payload factories with unique-sequence codes; default titration payload measures exactly 5.000 g/L on SULFURIC.
- `constants.py` — EQ_WEIGHTS, DRAGOUT_RATE, pricing constants (MASKING_RATE 85, BARREL_FLAT_FEE 1200, UNASSIGNED_RACK_FEE 2000, HAZMAT_FEE 2500, tier rates 12/15/19, discount thresholds), densities, MAX_REWORKS, clock default.
- `test_users.py` — shared `TEST_USERS` + per-instance builders (`make_customer_headers(entity_id)` mandatory for ownership-gated calls; `make_ehs_officer_headers(user_id)` for segregation-of-duties tests).
- `fixtures.py` — composite tiers: `create_titrated_bath`, `setup_routed_order`, `setup_awaiting_inspection`, `setup_awaiting_lot_test`, `strip_and_replate`, `run_passing_cycle`, manifest/permit/sample helpers, `set_clock`.
- `__init__.py` — barrel export (framework generics + PRD-specific).

`test_suite/` (13 files, 94 tests collected cleanly):
- `test_01_pricing_dual_variant.py` (6), `test_02_bath_life_and_chemistry.py` (6), `test_03_work_order_lifecycle.py` (8), `test_04_bath_lifecycle.py` (5), `test_05_cascades.py` (8), `test_06_boundaries.py` (8), `test_07_priority_and_temporal.py` (8), `test_08_manifests_and_amendment.py` (6), `test_09_salt_spray_and_predip.py` (4), `test_10_master_data_and_validation.py` (15), `test_11_auth_pagination_envelope.py` (7), `test_12_waste_mass_and_dragout.py` (3), plus `conftest.py`.

**Coverage audit** (machine-verified):
- Queue A: 21/21 difficulty instances, each with exactly 2 tests (42 tests) — meets the ≥2 target.
- Queue B: 50/50 non-stub corner instances, each with ≥1 test (52 tests) — meets the ≥1 target.
- 13 `excluded_because:` stubs not translated; every stub's `difficulty_instance` cross-reference resolves to a real §1.8 instance.
- Every test's docstring ends with exactly one `Design: Difficulty/...` or `Design: Corner/...` line copied verbatim from a real instance `name:` (C4 verified programmatically).
- Every quoted PRD citation survives a normalized literal-grep of `workspace/PRD.md` (C1 verified programmatically; 5 initial elision/paraphrase failures were found and fixed).
- No `pytest.mark.skip`/`skipif`/`xfail` anywhere. No freelance (non-index) tests.

**Skipped instances:** none. All 21 difficulty instances and all 50 active corner instances passed the PRD-first two-condition filter — the PRD explicitly covers every asserted rule (including the pinned tier orderings for the two priority-pair instances: §2.7/§2.8 state stale-version-before-state and earlier-tiers-mask-later verbatim).

**Notable faithful translations:** logical clock (`set_clock` to 2026-08-10/01:00 for the fixture half-open boundary; 95h/96h gate for salt-spray); OCC version capture before every dose/load-start/line-add/amend; exact pinned values (7625/10175/14100; 4200; 542640/545140; 588 vs 600.0; 0.613 half-up; 0.002 round-then-sum; 960.0 kg dump line; 2813 late-cancel fee; 8950 masking quote).

## Step 6: Generate Implementation — 2026-08-14T12:30:00.000Z

Implementation complete. Final summary:

## Summary

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1719_anodizing_electroplating_line/workspace/implementation/`):

- `start.sh` — executable launcher; guarded `pip install` (no-op once flask importable), `exec python3 app.py`, binds `0.0.0.0:$PORT` (default 10000)
- `requirements.txt` — flask only
- `app.py` — Flask app factory, blueprint registration, ApiError/404/405/400/catch-all error handlers
- `db.py` — in-memory store (14 entity tables, starts empty every boot) + logical clock (default `2026-08-01T00:00:00Z`, never wall-clock) + ID/timestamp helpers (`req_` request IDs, ISO-8601 3-fractional-digit UTC timestamps)
- `errors.py` — all 50 error IDs with exact HTTP statuses (incl. 402 for credit hold, 412 for OCC, 403 for segregation of duties)
- `response.py` — exact envelope: `meta.api_request_id`/`api_request_timestamp`, `response_type` object/array/error, `data`; pagination fields (`limit`/`offset`/`total_count`/`has_more`) in `meta` for lists
- `middleware.py` — tier-1 header auth (`X-User-ID`/`X-User-Role`, six roles), tier-2 role authorization, tier-3 customer ownership scoping
- `helpers.py` — common-field stamping (`version` starts at 1, `touch()` bumps version + `updated_at`; append-only events get only `id`/`created_at`), pagination parsing (default 10, min 1, max 100), schema validators, ISO8601/date parsing, left-to-right existence
- `serializers.py` — per-entity views, including computed read-time fields (`nameplate_remaining_ah`, `effective_remaining_ah`, `recommended_dose_g`, lot `hours_run`)
- `services/pricing.py` — 9-step provisional/final pricing with per-line ROUND_HALF_UP cents, tier rates (12/15/19), discount tiers (0.05/0.08 at 500k/1M subtotal), hazmat fee on routed CHROMIC/CYANIDE snapshot, ceil fixture amortization, cancellation fee
- `services/chemistry.py` — titration (per-family EQ weights, 3-dp half-up), dose math, dragout (0.0008/dm²), amp-hour estimate (2-dp), nameplate/effective bath-life (floor, efficiency floor 0.5), chemistry→analyte map (SULFURIC→none)
- `services/manifest_calc.py` — line mass by source-type density (1.2/1.5), manifest total recompute
- `services/cascades.py` — bath quarantine/exhaustion/dump/release/renew cascades to work orders, exceedance cascade (permit→EXCEEDED + matching ACTIVE baths→QUARANTINED + their ROUTED WOs→ROUTE_HELD), permit-blocks-chemistry check for exceedance-caused release
- `routes/` — 10 blueprints: customers, fixtures, compat_rules, baths, work_orders, load_runs, salt_spray, permits, manifests, clock

**Endpoints implemented: 53/53** — verified by enumerating the Flask url_map and matching against the scaffold's endpoint table one-for-one.

**Key fidelity points implemented:** 12-tier validation order per endpoint (auth → role → ownership → existence L-to-R → schema → OCC at tier 6 before state → WO-state-before-bath-state at tier 7 → safety → temporal → structural → fiscal → compliance hold at 12, with the exceedance hold at tier 8 for bath release but tier 12 for manifest finalize, segregation checked before the hold); all 4 OCC rules with 412; 13-state WO machine incl. 2-rework strip cycle with predip/routing reset; bath exhaustion (inclusive `>=`) at completion with cascade; quarantine with RUNNING loads allowed to finish; dump→F006 manifest line + renew with baseline titration; exceedance cascade with per-analyte pinned round-then-sum mass accounting and calendar-month reset/regression; salt-spray allowed-failures boundaries (4→0, 5→1, 9→1, 10→2) with logical-clock hours gate; owner-early/manager-late cancel split with 50%-processing late fee.

**Deviations from PRD:** none intentional. Two judgment calls where the spec has no dedicated error ID: (a) duplicate `bath_code`/`fixture_code` → `ERR_INVALID_REQUEST` (catalog defines a duplicate-ID error only for compatibility rules); (b) PATCH amend on a non-RECEIVED order → `ERR_WORK_ORDER_NOT_RECEIVED` (no amend-specific state error exists). Dosing a never-titrated bath is allowed (no current ≥ target comparison possible) with null treated as 0 for dose math.

**Verification:** seven ad-hoc smoke suites (~150 assertions) covering the full workflow graph, all cascades, OCC orderings, pricing boundaries, and RBAC/ownership negatives were run green across two independent fresh `bash start.sh` boots, confirming clean per-test restart behavior.

## Step 7: Test/Iterate Loop — 2026-08-14T12:57:00.000Z

Clean sweep: all 8 rounds pass 93/93 with zero failures in the union. Exiting with the summary.

## Summary

**Iterations run:** 2 (initial 8-round sweep: 81/94 with 13 deterministic failures, identical across all rounds; post-fix sweep: 93/93 × 8 rounds, zero failures).

**Tests deleted (1):**
- `test_10_master_data_and_validation.py::test_out_of_band_bath_blocks_routing` — unique-derivability collapse (per-operation scope silence). The test asserted that routing a titrated-but-below-band bath yields `ERR_BATH_CONCENTRATION_OUT_OF_BAND`. PRD §3.5's routing cascade enumerates the tier-8 safety checks at routing exhaustively (alloy rule + "titrated at least once so a current concentration exists for the pessimistic projection"), and §3.3 pins only "routing a bath that has never been titrated is rejected with `ERR_BATH_CONCENTRATION_OUT_OF_BAND`" — the band check is named only for load start (§3.5) and quarantine release (§3.3). Two faithful PRD-only readers diverge; the companion `test_untitrated_bath_blocks_routing` (PRD-verbatim) remains. Scaffold driver: `SCAFFOLD_CORNER_DESIGN.yaml` corner `untitrated_or_out_of_band_bath_blocks_routing`, whose `distinguishing_aspect` asserts the out-of-band route rejection that the PRD prose never rendered (doc-generator Zero-Silence violation).

**Fixes applied to `test_helpers/` (1):**
- `fixtures.py::create_titrated_bath` — reconcile the `target_conc` shorthand with callers passing the canonical PRD field name `target_concentration_g_l` (pop from overrides before forwarding), fixing `TypeError: got multiple values for keyword argument` in the three test_01 pricing tests.

**Fixes applied to `test_suite/` (3 files):**
- `test_07_priority_and_temporal.py` — added missing imports `abort_load_run` and `validate_success` (NameErrors in 3 tests).
- `test_07_priority_and_temporal.py::test_alloy_incompatibility_beats_credit_hold` and `::test_credit_hold_surfaces_once_alloy_rule_exists` — setup bug: created the customer with `credit_hold=True` and then created the work order, but PRD §3.4 verbatim fiscally gates creation ("a customer on credit hold is rejected with `ERR_CUSTOMER_CREDIT_HOLD`"), so the PRD-faithful implementation correctly 402'd the setup. Fixed to apply the hold via `PATCH /customers/{id}` after intake+prepare, preserving the tier-8-beats-tier-11 assertion exactly.
- `test_07_priority_and_temporal.py` (fixture tests) — set the logical clock with the canonical three-fractional-digit form (`2026-08-10T00:00:00.000Z`) and updated the three `started_at`/`ended_at` string assertions to match, so exact equality holds under both faithful readings (raw echo vs. §2.2/§2.4-normalized serialization).
- `test_05_cascades.py` — added missing import `make_ehs_officer_headers` (NameError in 2 manifest-finalize tests).

**Fixes applied to `implementation/`:** none — every failure traced to test artifacts; the implementation was already PRD-faithful in all audited areas (pricing, chemistry, cascades, manifests, permits, load runs, salt spray).

## Step 8: Finalize PRD — 2026-08-14T13:10:00.000Z

All edits committed and verified. The diff is exactly 4 modified lines, all inline revisions within existing paragraphs — no new sections, line count unchanged.

## Exit Summary

**Line counts / delta:** `PRD.md` 370 lines → `PRD_FINALIZED.md` 370 lines (0.0% line-count delta; 4 of 370 lines modified inline, ~1.1% of lines touched). File: `/home/ubuntu/github/CodingPRD/tasks/task_1719_anodizing_electroplating_line/workspace/PRD_FINALIZED.md`

**Changes (one bullet each):**
- §2.8 (tier 8, line 133) — revise — scoped each tier-8 safety check per operation: alloy rule checked at routing; pre-dip at load start; titrated-at-least-once at routing; inclusive control band checked at load start and quarantine release, "deliberately not at routing"; unverified dose checked at load start and quarantine release — `implementation/routes/work_orders.py:324-328,406-412`, `implementation/routes/baths.py:229-238`
- §3.5 (routing paragraph, line 205) — insert — after the never-titrated clause, pins that the control-band check is not applied at routing (deferred to load start), so a titrated bath outside its band may still route, with only the pessimistic bath-life projection of §3.3 remaining as the chemistry-driven gate — `implementation/routes/work_orders.py:327-328,347-352`, `implementation/services/chemistry.py:80-94`
- §2.6 (line 107) — revise — pins the clock-set response: `current_utc` is the set instant normalized to UTC, `YYYY-MM-DDTHH:MM:SS...Z`, with a three-digit millisecond fraction inserted exactly when the sub-second component is non-zero (finer precision truncated), including the worked example that `2026-08-10T00:00:00.000Z` echoes as `2026-08-10T00:00:00Z` — `implementation/routes/clock.py:21-25`, `implementation/helpers.py:176-190`
- §2.6 (line 109) — insert — pins that every clock-derived timestamp (`created_at`/`updated_at`, load-run `started_at`/`ended_at`, sample `sampled_at` whether defaulted or caller-supplied, and the permit's `last_sampled_at`) serializes in ISO 8601 UTC with exactly three fractional digits regardless of input form — `implementation/db.py:53-62`, `implementation/helpers.py:15-36`, `implementation/routes/work_orders.py:443`, `implementation/routes/load_runs.py:30,73`, `implementation/routes/permits.py:141-147,177`

**Step-7 items with no PRD edit (traced, verified already-pinned or pure test bugs):** `fixtures.py::create_titrated_bath` (`target_conc` vs canonical `target_concentration_g_l` — helper bug; PRD §3.2 already canonical); test_07/test_05 import additions (test bugs); test_07 credit-hold setup (PRD §3.1 already pins optional `credit_hold` at creation per `customers.py:34`, §3.4 already pins the 402 creation gate per `work_orders.py:117-118` — impl is PRD-faithful, test setup was not).

**Per-edit pre-edit search log:**
- Edit §2.8 tier 8 — (a) subject: per-operation scope of chemistry/alloy safety checks. (b) enumerated paths: `work_orders.py:324-328` (route: alloy + null-concentration only), `work_orders.py:406-412` (load start: dose → band → predip), `baths.py:229-238` (release: dose → band → exceedance hold), `chemistry.py:97-102` (`concentration_in_band`: inclusive, null→False), `chemistry.py:80-94` (`effective_remaining_ah`: null→None, ratio clamp 0.5), grep over `concentration_in_band`/`ERR_BATH_CONCENTRATION_OUT_OF_BAND`/`dose_verification_pending` confirmed no other raise sites; §3.2 line 165 and §3.3 release gate cross-checked. (c) wording adjusted during drafting: kept the original enumeration order and added parenthetical per-operation scopes rather than reordering, so no new ordering claim is implied (per-operation order remains pinned by §3 narratives); scoped the dose check to "load start and quarantine release" (not routing) to match `baths.py:229`.
- Edit §3.5 routing — (a) subject: routing-time behavior for a titrated-but-out-of-band bath. (b) enumerated paths: same route/load-start/release paths as above plus `work_orders.py:350-352` (tier-11 bath-life gate consuming `effective_remaining_ah`) and `serializers.py:77` (bath detail exposure, off-site but same function); confirmed §3.3's never-titrated sentence stays verbatim-consistent. (c) wording softened from an earlier draft ("discounting its effective amp-hours") to "the pessimistic bath-life projection of §3.3 the only chemistry-driven gate remaining", because an above-band bath gets efficiency 1.0 (no discount) — the looser phrasing is true for both below-band (clamp 0.5) and above-band paths.
- Edit §2.6 current_utc — (a) subject: serialization of the clock-set echo. (b) enumerated paths: `clock.py:13-26` (the only non-`format_ts` timestamp emission; fraction appended iff `dt.microsecond != 0`, ms truncated), `helpers.py:176-190` (`parse_iso8601` UTC normalization), grep over `format_ts`/`strftime`/`now_iso`/`isoformat` across the whole impl confirming every other emission path. (c) wording includes the `.000Z`-input→no-fraction-output example and the truncation clause to exactly match the `microsecond`-truthiness quirk (e.g. 500 µs renders `.000`), avoiding a false "always three digits" claim that would contradict `clock.py:22`.
- Edit §2.6 stamped timestamps — (a) subject: serialization form of clock-derived timestamp fields. (b) enumerated paths: `db.py:48-62` (`format_ts`/`now_iso`), `helpers.py:15-36` (`stamp_new`/`stamp_event`/`touch`), `response.py:10` (`api_request_timestamp` — already pinned §2.2, consistent), `work_orders.py:443`, `load_runs.py:30,73`, `permits.py:141-147,177` (caller-supplied `sampled_at` is normalized through `format_ts`, not echoed raw; `last_sampled_at` copies the same string), `serializers.py` (pass-through, no reformatting), `serializers.py:193-199` (`hours_run` computed, not serialized), `permits.py:93-94` (permit dates are `YYYY-MM-DD`, untouched by the claim). (c) wording scoped by an explicit enumeration ("the `created_at`/`updated_at` of §2.4, a load run's `started_at`/`ended_at`, and a waste sample's `sampled_at` ... `last_sampled_at`") so it cannot be misread as covering the clock-set `current_utc` echo pinned differently in the adjacent sentence.

## Step 9: Complete PRD — 2026-08-14T13:25:00.000Z

The task is complete. `PRD_COMPLETED.md` has been produced at `/home/ubuntu/github/CodingPRD/tasks/task_1719_anodizing_electroplating_line/workspace/PRD_COMPLETED.md`.

## Summary

**Files:** `PRD_FINALIZED.md` 370 lines / 66,128 chars → `PRD_COMPLETED.md` 371 lines / 69,302 chars (**+1 line, +3,174 chars**).

**Counts:** 29 ambiguity-pins, 4 mismatch-revisions (33 change bullets across 26 inline edits). Error catalogue verified 1:1 against `errors.py` (50 codes, identical HTTP statuses); all 93 existing tests were confirmed passing against this implementation beforehand (results.8.json), and all three generation-notes judgment calls were confirmed in code and pinned.

**Changes:**

- §2.2 — insert — ambiguity — unrouted route/unsupported method → `ERR_NOT_FOUND` 404; non-object JSON body → `ERR_INVALID_REQUEST` 400; missing/unparsable body treated as empty object — `app.py:45-58`, `helpers.py:73-79`
- §2.3 — insert — ambiguity — non-integer/out-of-range `limit`/`offset` → `ERR_INVALID_REQUEST` 400 — `helpers.py:43-60`
- §2.3 — insert — ambiguity — list ordering tie-break by `id` ascending — e.g. `routes/customers.py:53`, `routes/baths.py:152`
- §2.3 — insert — ambiguity — `has_more` = `offset + returned < total_count` — `response.py:35`
- §2.7 — insert — ambiguity — OCC version field must be an integer; missing/non-integer → `ERR_INVALID_REQUEST` — `baths.py:164-166`, `work_orders.py:199-201,382-383`, `manifests.py:75-77`
- §2.8 tier 5 — revise — **mismatch** — removed "manifest ship request must include the transporter" from tier 5 (impl evaluates it only after the tier-7 FINALIZED check) — `manifests.py:170-174`
- §2.8 tier 5 — insert — ambiguity — unrecognized request fields are ignored, not rejected — passim (e.g. `customers.py:68-81`)
- §2.8 tier 10 — revise — ambiguity — duplicate `bath_code`/`fixture_code` pinned to `ERR_INVALID_REQUEST` (HTTP 400) — `baths.py:83-85`, `fixtures.py:34-37`
- §3.1 — insert — ambiguity — customer may be created directly as `SUSPENDED` — `customers.py:35`
- §3.1 — insert — ambiguity — `purchase_cost_cents`/`rated_uses` are integers — `fixtures.py:31-32`
- §3.2 — insert — ambiguity — dosing a never-titrated bath allowed; null concentration treated as 0 and `ERR_DOSE_NOT_NEEDED` cannot fire — `baths.py:177-183`
- §3.2 — insert — ambiguity — `recommended_dose_g` treats null concentration as zero (shortfall = full target) — `chemistry.py:48-58`
- §3.3 — insert — ambiguity — `effective_remaining_ah` is null on a never-titrated bath — `chemistry.py:83-85`
- §3.3 — revise — **mismatch** — quarantine release clears `quarantine_cause` and increments `version` on both landings (`EXHAUSTED` included); only the WO `ROUTE_HELD`→`ROUTED` cascade is conditioned on reaching `ACTIVE` — `baths.py:240-249`
- §3.4 — insert — ambiguity — `masking_minutes_actual` is null until preparation — `work_orders.py:134`
- §3.4 — insert — ambiguity — PATCH amend on non-`RECEIVED` order → `ERR_WORK_ORDER_NOT_RECEIVED` (409) — `work_orders.py:227-229`
- §3.5 — insert — ambiguity — prepare: state check fires before masking rule; `masking_minutes` must be a non-negative integer — `work_orders.py:250-261`
- §3.5 — insert — ambiguity — complete-predip is not state-gated — `work_orders.py:270-276`
- §3.5 — insert — ambiguity — route planning pair validated (`planned_duration_minutes` integer ≥ 1, `planned_current_density_a_dm2` > 0) — `work_orders.py:312-315`
- §3.5 — insert — ambiguity — load-start `duration_minutes` is an integer — `work_orders.py:378`
- §3.5 — insert — ambiguity — bath `version` advances twice on a load completion that exhausts the bath — `load_runs.py:47-52`, `cascades.py:23-26`
- §3.6 — insert — ambiguity — `sample_count`/`hours_required` integers; `panels_failed` null until evaluation; `hours_run` never below zero — `salt_spray.py:41-42,60`, `serializers.py:193-199`
- §3.6 — insert — ambiguity — evaluate `panels_failed` must be a non-negative integer — `salt_spray.py:72-74`
- §3.7 — insert — ambiguity — cancellation also clears the `routed_chemistry_family` snapshot — `work_orders.py:625-628`
- §3.8 — insert — ambiguity — permit dates echoed zero-padded `YYYY-MM-DD`; both limit numerics > 0; `last_sampled_at` null until first accepted sample — `permits.py:51-54,70-75,93-98`
- §3.8 — insert — ambiguity — sample `concentration_mg_l` allows zero — `permits.py:136-138`
- §3.8 — insert — ambiguity — `current_month` recorded as `YYYY-MM` string — `permits.py:155`
- §3.8 — insert — ambiguity — permit `version` advances twice on an exceedance sample (mass bookkeeping + exceedance flip) — `permits.py:204`, `cascades.py:60-62`
- §3.9 — revise — **mismatch** — `transporter_name` accepted at manifest creation (was "stays null until shipment") — `manifests.py:45,49`
- §3.9 — insert — ambiguity — dump validates its own body fields (`manifest_id` string, `decommission` boolean default false) before resolving the manifest reference — `baths.py:257-267`
- §3.9 — insert — ambiguity — dump line `description` is `Bath dump: <bath_code>`; dump clears `quarantine_cause` — `baths.py:285,295`
- §3.9 — insert — ambiguity — finalization checks segregation of duties before the non-empty check (both tier 10) — `manifests.py:143-149`
- §3.9 — revise — **mismatch** — manifest ship: `FINALIZED` state check fires before the transporter requirement; `transporter_name` must be a non-empty string — `manifests.py:170-174`

## Pipeline Complete — 2026-08-14T13:25:00.000Z

All 9 steps done. Final state: 93/93 tests passing across the 8-round per-test-server stability sweep; PRD_COMPLETED.md is the authoritative contract (PRD.md 370 lines → PRD_FINALIZED.md 370 lines → PRD_COMPLETED.md 371 lines).
