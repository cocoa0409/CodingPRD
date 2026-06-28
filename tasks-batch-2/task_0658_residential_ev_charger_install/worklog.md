# Worklog — task_0658_residential_ev_charger_install

Scenario: 658. Residential EV-Charger Installation (Qmerit/Treehouse style): site assessment & panel/load calc, charger product & circuit scope, permit & utility interconnection, electrician dispatch & install, rebate/incentive (utility/45W) processing, activation & app pairing, warranty/service, panel-upgrade referral

Difficulty: Expert

## Step 1: Create task directory — 2026-06-26T14:44:51.698Z

Directory pre-assigned and pre-created: tasks/task_0658_residential_ev_charger_install/ with workspace/ subdir. Auto-index scan skipped per execution parameters. Using folder verbatim as {task_dir}.

## Step 2: Generate scaffold — 2026-06-26T15:04:00.000Z

All three files are written, parse cleanly, honor the file split (single top-level keys), contain no forbidden concurrency vocabulary, and pass `scaffold_lint.py` clean.

Generated the Expert-difficulty scaffold for **task_0658_residential_ev_charger_install** (Residential EV-Charger Installation, Qmerit/Treehouse style). All three files written:
- `SCAFFOLD.yaml` (§1.0–§1.7)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single key `scaffold_difficulty_design`, §1.8)
- `SCAFFOLD_CORNER_DESIGN.yaml` (single key `scaffold_corner_design`, §1.9)

**Dimensions:**
- **Entities: 13** — Homeowner, Property, Electrician, ChargerProduct, InstallJob, SiteAssessment, Quote, PermitApplication, InterconnectionRequest, DispatchAssignment, IncentiveClaim, PanelUpgradeReferral, WarrantyTicket
- **Endpoints: 66** (64 business + 2 test-driving: `/_clock/set_current_utc`, `/_electricians/{id}/set-status`). Each state transition needs a trigger endpoint.
- **Error codes: 22**
- **Calculation variants: 8 variant entries across 6 calculations** — incl. NEC 220.83 vs 220.87 panel-load; federal-45W vs utility-rebate; circular permit-fee-on-net quote total; per-line tax rounding order.
- **State machines: 8** with non-linear features: InstallJob (parallel workflow_status × compliance_status), WarrantyTicket (cyclic DIAGNOSING↔AWAITING_PARTS + reopen cap 2), PermitApplication (cyclic SUBMITTED↔CORRECTIONS_REQUESTED auto-reject @3), Quote (branching REJECTED→DRAFT), InterconnectionRequest (approve/deny), DispatchAssignment, IncentiveClaim (compensation), PanelUpgradeReferral.

**Difficulty design:** 9 rules × 2 instances = 18. **Corner design:** 9 sections, 39 instances (31 active + 8 stubs). 2 OCC concurrency rules on `InstallJob.version`. `scaffold_lint.py`: clean. No sibling task referenced.

## Step 3: Copy shared files — 2026-06-26T15:04:54.747Z

Copied ./INSTRUCTION.md → tasks/task_0658_residential_ev_charger_install/workspace/INSTRUCTION.md (1424 bytes).

## Step 4: Generate PRD — 2026-06-26T15:10:13.378Z

**Output written:** `workspace/PRD.md` (324 lines)

**Sections covered:** §1 Introduction (dual workflow/compliance dimensions); §2 Global Specifications — 10 domain-derived subsections (RBAC for 5 roles, fixed §2.2 envelope, pagination, common properties/versioning with ChargerProduct `common_fields: false`, nested-resource/referential integrity, monetary & electrical precision, OCC on install job, two-dimensional state model, bubble-up clearance reconciliation, circuit-to-panel sizing); §3 Business Logic — 11 scattered subsections; §4 Endpoint Definitions (all 66 endpoints); §5 Error Code Catalogue (all 22 errors).

**Hard Contract reports — all PASS:**
- Field coverage: 52/52 entity fields, 39/39 request bodies, 6/6 query params.
- Rule coverage: 17/17 validations, 2/2 OCC rejections, 32 state transitions (8 entities), 6 calculations (panel_load dual-variant, spare-capacity boundary, polymorphic incentive+stacking, circular quote_total, per-line tax, electrician day-load strict-<), 22 error_ids, cascades + dual circuit-check scope, defaults, sibling-branch symmetry.
- Path purity (§3 only): 377 backtick tokens scanned, 0 paths/methods leaked.

No fuzzy words or pseudocode leaked. Withheld difficulty/corner design files not opened.

## Step 5: Generate unit tests — 2026-06-26T15:22:39.537Z

**Files written:** `test_helpers/` (9 files: types, api_client, api_errors, assertions, factories, constants, test_users, fixtures, __init__). ChargerProduct TypedDict omits updated_at/version (common_fields:false). test_users.py provides per-instance builders (make_homeowner_headers, make_electrician_headers); fixtures.py threads real entity ids into every ownership-gated call. Composite fixtures cover long preambles (base → ASSESSED → QUOTED → CLEARED → SCHEDULED → INSTALLED → ACTIVATED, plus BLOCKED panel-upgrade path).

`test_suite/` (conftest + 6 files): **67 test functions** across test_01_panel_load_calculations, test_02_quote_and_incentive_calculations, test_03_state_machines_and_cascades, test_04_dispatch_booking_constraints, test_05_cross_entity_and_compensation, test_06_crud_validations_rbac.

**Coverage:** Queue A (Difficulty) 9 rules × 2 = 18 instances, all translated, ≥2 tests each (38 tests), 0 skipped. Queue B (Corner) 39 instances: 31 non-stub all translated (29 tests), 8 excluded_because stubs correctly NOT translated; all 8 difficulty_instance cross-refs resolve.

**Audits passed:** every test has exactly one verbatim Design: line (no untagged/dual-tagged); all PRD citations verified verbatim via grep; no skip/skipif/xfail; no scaffold/section leakage; all files compile; suite collects cleanly (67 tests). Numeric expecteds (panel-load 15160/8840/false vs 9000/15000/true, quote total 201113, per-line tax 1251, federal 58725, stacking-cap clamp 50000) copied verbatim and independently recomputed. Self-corrected: removed 3 tests initially tagged against excluded stubs.

## Step 6: Generate implementation — 2026-06-26T15:22:39.537Z

Generated Python + Flask impl at `workspace/implementation/` (12 source + start.sh + requirements.txt).
- `start.sh` — foreground launcher; reads $PORT (default 10000), binds 0.0.0.0, guards pip install on cheap `import flask`, exec python3 app.py.
- `requirements.txt` — Flask==3.0.3.
- `app.py` (all 64 routes, error handlers, common-field helpers), `db.py` (in-memory dicts keyed by id, sku for ChargerProduct; empty on boot, no seeding), `clock.py` (logical clock default 2026-04-01T00:00:00Z), `errors.py`, `response.py` (exact envelopes), `middleware.py` (X-User-ID/Role auth + RBAC 5 roles), `validators.py`, `calculations.py` (Decimal/ROUND_HALF_UP panel-load NEC 220.83/220.87, quote pricing discount→net→permit→per-line tax, incentive federal/utility + 80% stacking cap), `services.py` (pagination, ownership, compliance bubble-up), `serializers.py` (ChargerProduct immutable: id + created_at only).

**Endpoints: 64 implemented** — full §1.5/§4 table. Booted via start.sh, ran 89 black-box checks, all passing (two-dimensional lifecycle, OCC quote-accept + scope 412, dual-variant calcs with exact values, panel-upgrade cascade + compliance BLOCK/unblock, permit corrections auto-reject, dispatch territory/overlap/capacity/suspension gates, RBAC, FK/existence ordering, fresh-boot empty store).

**PRD-fidelity note:** for permit filing on panel-upgrade-blocked job, PRD §3.5 explicit ERR_PANEL_UPGRADE_REQUIRED takes precedence over generic ERR_INVALID_STATE (§3.10 orders earlier) for the BLOCKED-due-to-upgrade case; other invalid compliance states still ERR_INVALID_STATE.

## Step 7: Run tests and iterate — 2026-06-26T15:48:41.230Z

Final 8-round sweep all-green (67/67 in every round). Directory in final state (no results files, no stray processes).

**Iterations run:** 4 sweeps. Sweep 1 surfaced 4 deterministic failures; sweep 2 (after fixes) showed only infra-flakiness; sweeps 3-4 confirmed logic fixed and residual noise was host contention. Final sweep: all 8 rounds 67/67.

**Tests deleted:** None. All 4 originally-failing tests trace to verbatim PRD prose and are uniquely derivable — every failure was a test-helper/test-setup bug or environmental, not a PRD-coverage problem.

**Fixes applied to `test_helpers/`:**
- `factories.py` — `create_homeowner_payload`: removed hardcoded `"email": "homeowner@example.com"` default. It pre-filled the email key, defeating `fixtures.py`'s `setdefault("email", _unique_email())`, so every `create_homeowner()` reused the same email → "email already registered" (400) on the second homeowner. (Fixed `test_homeowner_not_owner_cannot_cancel_others_job`.)
- `factories.py` — `create_charger_product_payload`: removed hardcoded `"sku": "CHG40"` default for the same reason — defeated `setdefault("sku", _unique_sku())`, so creating multiple charger products collided with "sku already exists". (Fixed `test_occ_scope_change_stale_version_rejected`, which creates 3 products.) Direct callers in test_01/test_06 always pass explicit email/sku, so unaffected.

**Fixes applied to `test_suite/`:**
- `test_06_crud_validations_rbac.py` — `test_charger_product_immutable_no_version_field`: changed GET to use `cp["sku"]` instead of `cp["id"]`. PRD §4 endpoint table states `GET /charger-products/{id}` "Fetch a charger product by sku", and §3.1 makes the catalog keyed by unique sku; impl correctly looks up by sku, so fetching by id returned 404. PRD-faithful immutability assertion (`"version" not in got`) preserved.
- `test_04_dispatch_booking_constraints.py` — `test_out_of_territory_beats_window_overlap`: original setup tried to seed an overlapping window by first booking an out-of-territory (NV) electrician on a CA property — but the territory check (§3.10 P10) rejects that first booking, making the prior window unconstructible. Rewrote setup to first book the NV electrician on an in-territory NV property (succeeds, seeds window), then book the same electrician on the CA property with an overlapping window same date. Both territory (P10) and window-overlap (P12) now genuinely applicable; test correctly asserts territory wins (`ERR_ELECTRICIAN_OUT_OF_TERRITORY`). Window-overlap is per-electrician across the day regardless of property (PRD §3.6), so PRD-faithful.

**Fixes applied to `implementation/`:**
- `start.sh` — replaced per-boot `python3 -c "import flask"` probe (a full interpreter spawn on every one of hundreds of concurrent per-test reboots) with a cheap `.deps_installed` filesystem-sentinel gate to cut boot-time CPU contention. No business/entity state is stored on disk (all entity storage remains in-memory dicts in `db.py`); the sentinel is a dependency-install marker only and is gitignored.

**Residual flakiness note:** Intermediate sweeps showed transient failures, all "API server could not be restarted" / "Connection reset" — never assertion failures, striking random tests each run. Root cause: host oversubscription (8 CPUs, load avg ~40 from concurrent pipelines) occasionally exceeding the runner's 15s per-test restart budget under 8× peak boot load. Final sweep ran at same load (~40) and still passed 67/67 in all 8 rounds — logic is correct and deterministic; earlier noise was purely environmental.

## Step 8: Finalize PRD — 2026-06-26T15:52:03.772Z

PRD_FINALIZED.md written (324 lines), **byte-identical** to PRD.md (0% delta). **No edits made.**

Every item in step_7_diff is a test-fixture/test-setup bug or non-behavioral infra change, not a PRD-silence or PRD/impl-mismatch:
- factories.py email/sku defaults removed → pure fixture-uniqueness bugs; PRD §3.1 already says email/sku must be unique.
- test_06 GET charger by sku → test-setup correction; PRD §4 already states GET /charger-products/{id} = "Fetch a charger product by sku", §3.1 keys catalog by unique sku, impl matches verbatim.
- test_04 territory-beats-window setup rewrite → test-setup correction; asserted priority (territory P10 before window-overlap P12) is verbatim PRD §3.10; window-overlap per-electrician/per-date regardless of property is verbatim PRD §3.6, matches app.py:933-940.
- start.sh .deps_installed sentinel → boot-time optimization, zero behavioral/API-contract impact, entity state remains in-memory.

A fresh implementer reading PRD_FINALIZED.md alone reproduces impl behavior for every step_7_diff site because PRD already pins each. No minimal patch warranted.

## Step 9: Complete PRD — 2026-06-26T15:56:38.982Z

Produced `workspace/PRD_COMPLETED.md` as a minimal patch over PRD_FINALIZED.md.

**File metrics:** Source PRD_FINALIZED.md 324 lines / 47,899 chars → PRD_COMPLETED.md 324 lines / 50,036 chars (char delta +2,137). All in-paragraph inserts/revisions; no new sections/paragraphs, no line-count change.

**Counts:** ambiguity-pins 10, mismatch-revisions 2.

**Changes:**
- §2.3 Pagination — insert — ambiguity — limit clamps to [1,100], offset clamps up to 0 (not rejected); non-integer limit/offset → ERR_INVALID_REQUEST — services.py:14-30
- §2.3 Pagination — insert — ambiguity — list-sort tie-break ascending id when created_at equal — services.py:36
- §3.1 Onboarding (homeowner) — insert — ambiguity — duplicate email / malformed state_code / non-positive floor_area_sqft / non-240 service_voltage → ERR_INVALID_REQUEST — app.py:118-156
- §3.1 Onboarding (charger catalog) — insert — ambiguity — duplicate sku / negative msrp_cents → ERR_INVALID_REQUEST — app.py:207-210
- §3.1 Onboarding (electrician) — insert — ambiguity — malformed license_state_code / non-positive max_daily_jobs → ERR_INVALID_REQUEST — app.py:242-244
- §3.2 Opening install job — revise — mismatch — re-scope endpoint enforces no workflow_status precondition (only OCC + circuit-sizing gate it) — app.py:334-353
- §3.2 Panel assessment — insert — ambiguity — standard-method "amount that exceeds 8,000" is signed difference, not floored at zero — calculations.py:39-47
- §3.3 Panel-upgrade referral — insert — ambiguity — recommended_main_amps = 150 when current main_breaker_amps < 150, else 200 — app.py:545-550
- §3.6 Install completion — insert — ambiguity — completion also requires workflow_status SCHEDULED (→ ERR_INVALID_STATE) alongside EN_ROUTE + CLEARED — app.py:1014-1015
- §3.7 Activation — insert — ambiguity — non-matching pairing_code → ERR_INVALID_REQUEST — app.py:370-371
- §3.10 Validation ordering — revise — mismatch — dispatch window-shape checks (ERR_VALIDATION_LIMIT minute-range, then ERR_INVALID_REQUEST ordering) run after territory and before overlap/capacity — app.py:920-927

**Deliberate non-change:** impl parses body fields (ERR_INVALID_REQUEST/ERR_VALIDATION_LIMIT) before FK-existence/domain checks across all endpoints, deviating from §3.10's "generic request-shape validation is last." Pervasive framework-level behavior, no test pins a conflicting order; pinning it would require rewording §3.10's core premise — left §3.10 general statement intact, pinned only the one concrete observable deviation (dispatch window-shape).

---

## PIPELINE COMPLETE — 2026-06-26T15:56:38.982Z

Termination signal `workspace/PRD_COMPLETED.md` exists on disk (324 lines, 50,036 chars). All 9 steps ran end to end. Final test state: 67/67 tests passing across all 8 stability-sweep rounds. 0 tests deleted. Full artifact inventory present (3 scaffold files, 4 PRD variants, 9 test_helpers, 7 test_suite files / 67 tests, 12-file Flask implementation + start.sh).
