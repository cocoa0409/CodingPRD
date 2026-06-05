# Worklog — task_0053_general_practice_ehr

## Step 1: Create Task Directory — 2026-05-30

Created `tasks/task_0053_general_practice_ehr/` and `tasks/task_0053_general_practice_ehr/workspace/`. Pre-assigned index 0053 used verbatim (no ./tasks/ scan, per parallel-run instruction).

## Step 2: Generate Scaffold — 2026-05-30

All three artifacts are complete and consistent. The lint passes clean, all `excluded_because` stubs cite valid §1.8 instances, names are unique, and no forbidden concurrency vocabulary appears.

Generated the full scaffold for **task_0053_general_practice_ehr** (General Practice EHR & Visit) — three files. `scaffold_lint.py` reports **VERDICT: clean lint** (300 calls across §1.8+§1.9, all FK reverse-reachability satisfied).

**Complexity profile:** compliance_audit + workflow_orchestration; flat topology; branching state machines; peer_roles; layers = optimistic_concurrency, cascading_side_effects, dual_variant_calculation, derived_field_reconciliation. Expert-tier surface.

**SCAFFOLD.yaml (§1.0–§1.7):**
- **9 entities:** Provider, Patient, CptCode (immutable, `common_fields:false`), Visit, ChargeLine (nested under Visit), Prescription, Referral, PortalAccount, HedisMeasure. 11 FKs, all with reverse-reachability GETs.
- **6 state machines:** Provider, Patient, Visit (branching + CODED↔IN_PROGRESS reopen cycle), Prescription (EPCS DRAFT→…→DISPENSED with PENDING_SIGNATURE→DRAFT revise cycle), Referral (REQUESTED forks AUTHORIZED/DENIED, expiry), PortalAccount (ACTIVE↔SUSPENDED cycle + auto-suspend on token lockout). 1 concurrency rule (OCC panel-bind on Provider.version → ERR_STALE_VERSION 412).
- **9 calculations:** charge_line_amount (tiered EM multiplier), visit_billed_total (provisional vs final, pinned round-per-line-then-sum), hedis_compliance_rate (administrative vs hybrid), hedis_eligibility (age/sex windows), panel_size, patient_lifetime_charges, patient_outstanding_balance, open_care_gaps, referral_auth_window.
- **16 validations** (priority-ordered, 8 categories), **18 errors**, **5 roles** (FrontDesk/Biller/QualityAnalyst opaque; Provider/Patient entity_backed), **61 endpoints** (incl. one `/_clock/set_current_utc` test-driving endpoint).

**SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8):** all 9 Difficulty Rules × 2 instances = **18 instances**, each with executable setup_api_calls chains and formula-derived literal asserts.

**SCAFFOLD_CORNER_DESIGN.yaml (§1.9):** **46 instances across 9 sections** (37 active + 9 `excluded_because` stubs, all citing valid §1.8 instances).

## Step 3: Copy Shared Files — 2026-05-30

Copied `./INSTRUCTION.md` → `tasks/task_0053_general_practice_ehr/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-05-30

Generated `workspace/PRD.md` (297 lines) — prose PRD for the General Practice EHR & Visit API.

**Section structure:** §1 Introduction (3 paras); §2 Global Specs (9 subsections: RBAC, fixed envelope, Pagination, Common Resource Properties & Versioning, Cross-Entity Reconciliation & Derived Fields, Nested Resource Retrieval, Monetary/Rounding, OCC on Panel Binding, Validation Ordering); §3 Business Logic (11 subsections by entity lifecycle); §4 endpoint table (61 endpoints, 4 cols); §5 error table (18 errors, 2 cols).

**Coverage:** all 9 entities + every field name verbatim; all 61 endpoints with authorized-role sets; all 18 error IDs surfaced near triggers; all 26 state values + transitions (incl. cyclic edges); all 9 calculations reconstructed step-for-step (EM multiplier map 0.5/0.8/1.0/1.4/2.0, pinned round-per-line-then-sum, final 10% write-down ×0.90, HEDIS rate ×10000÷denom round-half-up÷100 integer-0-on-empty, age eligibility floor days÷365.25 inclusive windows + sex gate, referral auth 90/14 days, vaccine 28-day spacing, lockout threshold 3, adherence min 1 fill, measurement year 2026).

**Information-scattering:** OCC fully in §2.8 + re-grounded §3.1 (stale-version framing, no race vocabulary); panel-bind check ordering explicit in §3.1; validation priority ordering global rule §2.9; both cascade chains previewed §2.5 + detailed at origins. §3 path-purity: 0 HTTP methods/URLs in §3 backticks. All three hard contracts PASS.

## Step 5: Generate Unit Tests — 2026-05-30

**Tests emitted: 71 total** (across 9 test files), all tagged and traceable to a single design-index instance.

**Queue A (Difficulty):** 34 tests covering **17 of 18** instances, exactly 2 tests each.
- **1 instance skipped:** `cross_entity_state_dependency/visit_checkin_requires_active_provider`. PRD §3.4 says check-in "is permitted only when... the rendering provider is `ACTIVE`," but never names the error fired when the provider is INACTIVE. ERR_INVALID_STATE (per §2.9) is defined as the *visit's own* transition legality — the visit is still validly SCHEDULED, so two PRD-only readers could reasonably return ERR_INVALID_STATE, a business-rule error, or ERR_FORBIDDEN. Fails unique derivability → skipped as a PRD gap (no weakening, no xfail).

**Queue B (Corner):** 37 tests, **all 37 non-stub instances** covered (≥1 each). The 9 `excluded_because:` stubs were not translated; all 9 cross-references were verified to resolve to real difficulty instances.

**Notable adjudication:** The `dual_variant_calc/hedis_administrative_vs_hybrid_rate_diverge` setup was re-derived. The YAML's pre-computed expected values (admin numerator 1) depend on a finalize-cascade flip whose "matching HEDIS measure" wording leaves open whether a PHYSICAL visit satisfies a `BCS_MAMMOGRAM` measure. Kept the same instance and Design tag but built the population purely from the unambiguous `chart_confirmed` mechanism (PRD §3.10): admin 0/4→0.0, hybrid 1/4→25.0. The `referral_auth_window` expiry assertion compares the parsed instant rather than the raw string.

**Verification:** all helper + test modules byte-compile; all 9 test modules import cleanly against a stubbed framework; 69 distinctive citation substrings confirmed verbatim in PRD.md; every test function carries exactly one well-formed `Design:` line.

**File layout:** `test_helpers/` — `__init__.py` (barrel, 114 exports), `types.py`, `api_client.py`, `api_errors.py` (18 error IDs), `assertions.py`, `factories.py`, `constants.py`, `test_users.py`, `fixtures.py`. `test_suite/` — `conftest.py` + 9 domain files (billing_calculations, visit_lifecycle, prescriptions_epcs, cascades_ledger, referrals_panel, scheduling_vaccine, hedis, crud_validation, portal_rbac_errors).

## Step 6: Generate Implementation — 2026-05-30

Built a complete Python + Flask implementation at `workspace/implementation/`.

**File layout:** `start.sh` (reads $PORT, binds 0.0.0.0, exec foreground), `requirements.txt` (flask==3.0.3), `app.py`, `db.py` (in-memory stores + logical clock + id/timestamp helpers), `errors.py` (APIError + 18 error-id constants), `response.py` (envelope §2.2), `middleware.py` (X-User-ID/X-User-Role auth 401 + RBAC 403), `validation.py` (field/type/enum → ERR_INVALID_REQUEST 422), `routes/` (common, providers, patients, cpt_codes, visits, prescriptions, referrals, portal_accounts, hedis, clock), `services/` (calc.py Decimal money math + HEDIS; derive.py cross-entity recompute + serializers).

**Storage model:** In-memory only — plain Python dicts keyed by UUID in `db.py`. No SQLite, no file/JSON dump, no /tmp cache. Stores start empty on every fresh boot — nothing seeded/preloaded/hardcoded. Logical clock defaults to wall time, set via API. Derived fields recomputed from source rows on read and on cascade triggers.

**start.sh:** Reads `$PORT` (default 10000), `app.run(host="0.0.0.0", ...)`, `exec python3 app.py` foreground. Verified boots via `bash start.sh`, binds 0.0.0.0, stores empty (total_count=0) on fresh boot.

**Judgment call:** no-show timing gate and referral-expire timing gate have no dedicated error ID in scaffold/PRD, so both map to `ERR_INVALID_STATE` (409), consistent with being state-transition guards.

## Step 7: Run Tests and Iterate — 2026-05-30

**Iterations run:** 2 (1 diagnostic baseline sweep → fixes → 1 confirming sweep). Both the first and final sweeps were deterministic — the same 3 tests failed in all 8 rounds of the baseline, and all 71 passed in all 8 rounds after fixes. No flakiness observed.

**Tests deleted:** None. All three failures traced to PRD-covered, uniquely-derivable rules.

**Fixes applied to test_suite/** (`test_05_referrals_panel.py`):
- `test_first_bind_at_capacity_one_succeeds` → renamed `test_first_bind_below_capacity_succeeds`; `test_second_bind_at_capacity_one_rejected` → renamed `test_bind_reaching_capacity_rejected`. Both originally used `panel_capacity=1` and asserted that capacity=1 admits exactly one patient. That contradicts the verbatim PRD §3.1 prose: *"if completing the bind would make the provider's `panel_size` reach or exceed `panel_capacity`, the bind is rejected"* — which uniquely determines `prospective >= capacity` rejection, so with capacity=1 the **first** bind is already rejected (it reaches 1). STEP-2 assertion mis-translation: off-by-one ("current size >= capacity") reading carried over from the design YAML's distinguishing_aspect. Fixed to `panel_capacity=2`: first bind (prospective 1 < 2) succeeds, second bind (prospective 2 >= 2) rejected with `ERR_PANEL_AT_CAPACITY`. Implementation correct per PRD, left unchanged.

**Fixes applied to implementation/** (`routes/patients.py`, `record_payment`):
- Changed the success status code from `201` to `200`. PRD §6 states verbatim: *"Operations that modify an existing resource — including every state transition, payment recording, panel binding, and measure exclusion — return `200 OK`."* Recording a payment modifies the existing patient ledger, so 200 is uniquely required. The test (`test_payment_compensates_balance_to_zero`) was faithful; implementation was wrong.

Final state per subagent: 71/71 passing across all 8 parallel rounds.

### Orchestrator post-verification + boot-robustness fix — 2026-05-30

On independent orchestrator re-run of the 8-round parallel sweep, 1–2 tests per round were NOT passing — `status: error`, `failed: 0`, `error_message: "API server ... could not be restarted before <test>"` (≈15s restart-timeout, union: `test_provider_start_visit_not_owner`, `test_provider_cannot_finalize_visit`, `test_authorize_already_authorized_referral_rejected`, `test_patient_cannot_create_visit`). Root cause: `start.sh` ran `python3 -m pip install -q -r requirements.txt` on **every** boot; under per-test-server isolation the server restarts before each of 71 tests × 8 concurrent rounds, so up to 8 concurrent pip invocations contended on the shared package cache/site-packages and intermittently blew past the restart readiness window. This is a boot robustness issue, NOT an assertion failure, and was invisible to the subagent's lower-contention run.

**Fix applied to implementation/** (`start.sh`): guarded pip behind an importability check — `python3 -c "import flask" >/dev/null 2>&1 || python3 -m pip install -q -r requirements.txt`. First boot still installs Flask (satisfies INSTRUCTION "installs all dependencies"); every per-test restart becomes an instant `exec python3 app.py`. PRD-neutral: no endpoint/field/side-effect/data change — purely makes boot fast and contention-free.

**Confirming sweep after boot fix:** all 8 parallel rounds **71/71 passed, 0 failed, 0 errors**. `results.{1..8}.json` persisted.

## Step 8: Finalize PRD — 2026-05-30

`PRD_FINALIZED.md` produced as an exact (byte-identical) copy of `PRD.md`, with **zero edits** — confirmed via `diff`. Both Step 7 items are non-silences where the PRD already uniquely determines the behavior the implementation now exhibits.

- **Line counts:** PRD.md = 297, PRD_FINALIZED.md = 297. Delta 0 (0.0%).
- **Item (a) — panel-bind off-by-one (test_suite-only):** pure fixture bug; impl already PRD-faithful per §3.1 "reach or exceed `panel_capacity`" (prospective `>= capacity`). Enumerated `routes/providers.py:129-169` bind_panel + panel-size callsites + `services/derive.py`. No edit.
- **Item (b) — record_payment 201→200:** PRD §6 already states verbatim "Operations that modify an existing resource — including every state transition, payment recording, panel binding, and measure exclusion — return `200 OK`." Cross-checked all modify-existing endpoints (panel bind, measure exclude, visit/prescription/referral/portal transitions) return 200; creation endpoints 201. No edit.
- **start.sh fix:** PRD-neutral boot guard, no edit.

Outcome PRD_FINALIZED.md == PRD.md is correct per the method's own note.

## Step 9: Complete PRD — 2026-05-30

Produced `PRD_COMPLETED.md` as a minimal patch over `PRD_FINALIZED.md`. Source 297 lines / 44,020 chars → 299 lines / 47,419 chars (+2 lines, +3,399 chars). Section headers unchanged (27→27); all edits in-paragraph.

**Counts:** 7 changes — 5 ambiguity-pins, 2 mismatch-revisions.

**Per-change:**
- §2.3 Pagination — insert — ambiguity — pinned optional equality-filter query params per collection — `routes/providers.py:99-104`, `routes/patients.py:78-83,134-190`, `routes/cpt_codes.py:64-66`, `routes/visits.py:113-121`, `routes/prescriptions.py:79-82`, `routes/referrals.py:81-84`.
- §2.5 Derived Fields — revise — mismatch — carved out blanket "derived recompute bumps version" rule: neighbor count recomputes (patient `open_care_gaps` on HEDIS create/exclude; former provider `panel_size` on patient deactivate) update in place WITHOUT bumping that neighbor's `updated_at`/`version` — `routes/hedis.py:67,88-90`, `routes/patients.py:106-108`.
- §3.2 Patient ledger — insert — ambiguity — former PCP `panel_size` recompute on patient deactivate leaves provider `version`/`updated_at` untouched — `routes/patients.py:106-108`.
- §3.3 Charge pricing — insert — ambiguity — `em_level` on a non-E/M code persisted as given but ignored by amount calc (multiplier 1) — `routes/visits.py:147-170`, `services/calc.py:42-51`.
- §3.6 Finalization cascade — insert — ambiguity — "matching HEDIS measure" = every GAP measure of current year (2026) flipped regardless of `measure_type`/`eligible`, one pass — `routes/visits.py:298-308`.
- §3.8 Referrals — insert — ambiguity — expire before window elapses yields `ERR_INVALID_STATE` — `routes/referrals.py:139-144`.
- §3.10 HEDIS exclude — insert — ambiguity — exclude reachable from any non-EXCLUDED status; already-EXCLUDED yields `ERR_INVALID_STATE` — `routes/hedis.py:84-85`.
- §4 endpoint table (`GET /patients/{id}/portal-account`) — revise — mismatch — fetch returns paginated `array`-type envelope (0-or-1), not single `object` — `routes/patients.py:196-205`.

Pipeline complete. Final test state: 71/71 across 8 parallel rounds, 0 failed, 0 errors.
