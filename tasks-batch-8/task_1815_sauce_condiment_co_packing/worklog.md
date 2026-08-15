# Worklog — task_1815_sauce_condiment_co_packing

## Step 1: Create Task Directory — 2026-08-14T18:18:00.000Z

Created `tasks/task_1815_sauce_condiment_co_packing/` and `tasks/task_1815_sauce_condiment_co_packing/workspace/` (completed by pipeline launcher before orchestrator start).

## Step 2: Generate Scaffold — 2026-08-14T18:59:56.000Z

All checks pass. Final state of the scaffold generation:

## Files written

- `/home/ubuntu/github/CodingPRD/tasks/task_1815_sauce_condiment_co_packing/SCAFFOLD.yaml` — §1.0–§1.7 (response envelope, entities, state machines, concurrency rules, calculations, validations, endpoints, errors, roles); contains neither `scaffold_difficulty_design` nor `scaffold_corner_design` keys
- `/home/ubuntu/github/CodingPRD/tasks/task_1815_sauce_condiment_co_packing/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level `scaffold_difficulty_design:` key (§1.8)
- `/home/ubuntu/github/CodingPRD/tasks/task_1815_sauce_condiment_co_packing/SCAFFOLD_CORNER_DESIGN.yaml` — single top-level `scaffold_corner_design:` key (§1.9)

## Counts

- **Entities:** 11 — CustomerAccount, Formula, IngredientSupply, PilotCell, ScaleUpTrial, ProcessAuthorityLetter, KettleLine, PackagingComponent, ProductionRun, QualityHold, LabelApproval
- **State machines:** 6 (Formula cyclic revision loop; ProductionRun cyclic rework loop; ScaleUpTrial/LabelApproval branching; ProcessAuthorityLetter supersede; QualityHold fork with divergent per-disposition side effects)
- **Endpoints:** 43 (all under flat `/copack/*` collections; every FK has a reverse-reachability GET)
- **Error catalog:** 42
- **Calculations:** 8 (incl. dual-variant run charge, hold deviation metrics, allergen-conditional changeover fee, two interval-overlap rules)
- **Difficulty instances (§1.8):** 18 — 9 rules × 2, all differentiation clauses honored (different entity domains, modes a vs b, different error-category pairs, different metrics/endpoints, different entity pairs, different interval semantics/resources, different conserved quantity types)
- **Corner instances (§1.9):** 46 entries = 32 full test recipes + 14 `excluded_because:` stubs citing §1.8 instances
- **Concurrency rules:** 2 (OCC `expected_formula_version` on PUT formula, `expected_component_version` on PUT packaging component)
- **Lint:** `VERDICT: clean lint` — 551 calls scanned, zero violations (final run pasted verbatim above)

## Design decisions worth noting

- **No logical clock**: all scheduling uses explicit ISO8601 datetimes in payloads, keeping every time-gated rule deterministic without a `/_clock` endpoint.
- **Letter-exempt path**: `process_category: ACID` auto-approves a formula at trial pass; ACIDIFIED/LOW_ACID require an ACTIVE process-authority letter pinned to `formula.revision` (version-pinning layer).
- **Deliberately dropped `ERR_PROCESS_LETTER_NOT_ACTIVE`**: the reformulate cascade (APPROVED→DRAFT supersedes the letter and auto-cancels PLANNED/CONFIRMED runs) makes a stale-letter confirm unreachable, so the error would have been dead catalog weight.
- **Boundary-direction contrast**: pH deviation is strict `>` (equality compliant) while water-activity deviation is `>=` (equality triggers) — both pinned in `hold_deviation_metrics`.
- **Rule 8 contrast**: kettle lines use allergen-conditional 4h/1h buffered intervals (touching never allowed); pilot cells use zero-buffer half-open intervals (touching allowed).
- **Disposition governance**: `disposition_owner` copied from the customer default routes disposition to Customer vs QAReviewer; segregation-of-duties forbids the hold's creator from dispositioning it; statutory ceilings (pH 4.6, aw 0.85) force DESTROY-only when breached.
- **Size note**: 43 endpoints exceeds the Expert guideline band (20–32) — driven by the scenario's eight headline workflows plus linter-required FK reverse-reachability GETs; entity count stays at 11 with density in the coupling (cascades, OCC, dual-variant pricing) rather than more tables.

## Step 3: Copy Shared Files — 2026-08-14T19:00:19.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1815_sauce_condiment_co_packing/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-14T19:10:00.000Z

PRD generated and verified. Summary follows.

## Output
- **File**: `/home/ubuntu/github/CodingPRD/tasks/task_1815_sauce_condiment_co_packing/workspace/PRD.md` — 301 lines

## Sections produced
- **§1 Introduction** (2 paragraphs — business-context + role-tension angle)
- **§2 Global Specifications** (7 subsections): 2.1 RBAC with per-role `identity:` translation (Customer entity-backed by `CustomerAccount`; OpsAdmin/ProcessAuthority/QAReviewer opaque); 2.2 API Response Structure (byte-identical verbatim block, confirmed by diff against `section-2.2-response-structure.md`); 2.3 Pagination (`limit` 10/1/100, `offset` 0, `created_at` ascending, meta fields); 2.4 Common Resource Properties; 2.5 OCC; 2.6 Money/Measurements/Rounding (whole-cent half-up per-line for charges, 2-decimal half-up for deviation metrics); 2.7 Validation Order (explicit 10-stage pipeline with precedence rule)
- **§3 Business Logic** (8 subsections, lifecycle-grouped): customer/formula intake → pilot trials → letters/approval/reformulation → resources/run planning → confirmation (changeover fee, kettle interval rule, availability, estimate, credit) → completion (final charge, auto-hold) → holds/disposition → labels/release
- **§4 Endpoint table**: 43 rows, 4 columns only
- **§5 Error catalogue**: 42 rows, 2 columns only (statuses from `errors[]`; `ERR_INVALID_PROCESS_LIMITS` and `ERR_LABEL_ALLERGEN_MISMATCH` listed as 422 per the error catalog, which overrides the validation table's generic 409)

## Hard contract reports

```
Field coverage check:
- entities[].fields + endpoint inputs + query params: 69 required, 69 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 10 checked, 10 expressed (§2.7 staged pipeline + per-endpoint order notes in §3), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write op + expected_formula_version/expected_component_version + ERR_STALE_VERSION 412 named), 0 missing
- state_machines[].transitions: 23 checked across 6 machines, 23 fully expressed (from/to, preconditions+error ids, side effects), 0 missing
- calculations[]: 8 checked, 8 fully expressed in precise prose (constants 75000/15000, 4h/1h, 4.6/0.85 embedded; boundary inclusivity preserved: aw deviation is reach-or-exceed vs pH exceed-only; shortage/credit tests strict-greater with equality allowed), 0 missing
- validations[] conditions: all matchable to error ids in §2/§3 prose, 0 missing
- endpoints[].side_effects / applies_to: all expressed (reformulate cascade, confirm postings, cancel unwind, DESTROY sweep + refund, activation supersede), 0 missing
- entities[].fields[] structured content: defaults, initial values, nullability, and numeric constraints reconstructible from prose, 0 missing
- sibling-branch symmetry: RELEASE/REWORK/DESTROY, PASSED/FAILED/CANCELLED, both OCC rules — equal density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 466
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

## Decisions worth noting
- §3 organized by lifecycle (8 subsections); endpoint paths/methods named only in §2.5 (OCC contract) and §4, with §3 using state-transition framing and role+verb phrasing exclusively.
- The disposition validation ordering is non-obvious in the scaffold (statutory gate at priority 7 precedes owner routing/segregation at priority 8) — made explicit in §3.7 so a PRD-only reader gets the order right.
- Error table uses the `errors[]` catalog statuses (422 for process-limits and allergen-mismatch), and the same statuses were used in §2.7 prose for consistency.
- A mechanical verifier was run (fenced code blocks stripped before tokenization — naive extraction desynchronizes on §2.2's JSON fences); the two withheld files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened or referenced.

## Step 5: Generate Unit Tests — 2026-08-14T19:35:00.000Z

Done. Summary of the generated test infrastructure for task_1815_sauce_condiment_co_packing:

## Files written

**test_helpers/** (9 files, all under `/home/ubuntu/github/CodingPRD/tasks/task_1815_sauce_condiment_co_packing/test_helpers/`):
- `types.py` — 11 entity TypedDicts (all carry the PRD §2.4 common fields), 11 domain/status enums, `UserRole`
- `api_client.py` — `ApiClient(GenericApiClient)` with all 43 endpoints from PRD §4
- `api_errors.py` — all 42 `ApiErrorId` values with the §5 HTTP status map, registered via `set_error_http_status_map`
- `assertions.py` — per-entity `assert_*` (common-field formats + status membership + PRD-named typed fields; `on_hand >= reserved` invariant; `available_units` checked only when serialized)
- `factories.py` — payload factories for all 11 creatable resources, input fields only
- `constants.py` — 15000/75000 changeover fees, 1h/4h gap hours, 4.6/0.85 statutory ceilings
- `test_users.py` — `TEST_USERS` for the three opaque roles plus a non-ownership Customer fallback; `make_customer_headers(user_id)` for the entity-backed Customer role and per-user QA/PA builders (segregation-of-duties tests pin `qa-7`/`qa-9`)
- `fixtures.py` — ~30 helpers: single-call creators/readers plus composites `setup_approved_acidified_formula` (Chain A: customer → ACIDIFIED formula with pepper/vinegar supplies + 5000 consigned → trial passed → letter rev1 ACTIVE → APPROVED), `setup_approved_acid_formula` (auto-approve chain, parameterizable supplies), `setup_trial_passed_formula`, `setup_confirmed_run`, `setup_run_on_hold`, `setup_completed_clean_run`, `setup_nut_and_none_formulas` (dual-formula allergen chain)
- `__init__.py` — barrel export

**test_suite/** (`conftest.py` + 6 files, 68 tests total):
- `test_01_formula_intake_and_catalog.py` (9), `test_02_scale_up_trials.py` (8), `test_03_compliance_gates.py` (9), `test_04_run_planning_and_confirmation.py` (19), `test_05_completion_and_billing.py` (10), `test_06_quality_holds_and_disposition.py` (13)

## Test counts per source
- **Queue A (Difficulty): 36 tests** — all 18 instances × exactly 2 tagged tests each
- **Queue B (Corner): 32 tests** — all 32 non-stub instances × 1 tagged test each
- All 14 `excluded_because` stubs left untranslated; every stub's `difficulty_instance` cross-reference verified to resolve

## Instances skipped
None. Two instances had a single underivable sub-assertion dropped rather than weakening the test: the `version == 1` initial-value claim in `Corner/entities/customer_create_applies_defaults` and `Corner/state_machines/formula_initial_state` — PRD §2.4 defines `version` as a counter that "increments with every modification" but never pins its initial value (two-reader failure). All other asserted values (COPACKER default, outstanding 0, DRAFT, revision 1) are verbatim PRD-covered and retained.

## Stage 2 self-audit results
- Tag coverage script: PASS — 68/68 tags resolve to real instances; every difficulty instance ≥2 tests; every non-stub corner instance ≥1; zero tests tagged to stubs; zero unknown tags
- Citation audit: PASS — 105 quoted sentences across 68 docstrings all survive whitespace-normalized literal match against PRD.md; every docstring ends with exactly one `Design:` line
- `py_compile` on all 15 files: OK; `pytest --collect-only`: 68 tests collected cleanly; `test_helpers` imports against the installed framework

Notable PRD-derived pins: estimate/final divergence (859000 → 774600), per-line round-half-up before sum (15006 vs 15005), 4h allergen kettle buffer boundary-inclusive, aw ≥ boundary triggering holds (dev 0.0, margin −0.05), statutory gate evaluated before actor checks, and the reformulate/destroy cascade values, all literal from the design indices and verbatim-cited to PRD prose.

## Step 6: Generate Implementation — 2026-08-14T19:35:00.000Z

Implementation complete and verified. Summary follows.

## Files written (all under `/home/ubuntu/github/CodingPRD/tasks/task_1815_sauce_condiment_co_packing/workspace/implementation/`)

- `start.sh` — foreground launcher with guarded pip install (no-op once flask importable), `exec python3 app.py`, honors `PORT` (default 10000), binds `0.0.0.0`
- `requirements.txt` — `flask>=3.0,<4`
- `app.py` — Flask app factory, `/copack` auth hook, error handlers (ApiError / 404 / 405 / catch-all)
- `db.py` — in-memory store, 11 entity dicts, monotonic seq; starts empty, zero seeding
- `errors.py` — ApiError + all 42 catalog error IDs (plus a fallback `ERR_NOT_FOUND` for unmatched routes)
- `util.py` — ISO-8601 parsing, 3-fractional-digit UTC formatting, typed body validators
- `response.py` — envelope (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`), list pagination fields (`limit`/`offset`/`total_count`/`has_more`, default 10, clamp 1–100)
- `middleware.py` — `X-User-ID`/`X-User-Role` auth (4 roles), role gating, Customer ownership-chain scoping
- `services/core.py` — record stamping, `touch` (version++ / updated_at), serialization, per-resource 404 finders
- `services/calc.py` — all money/interval/deviation math
- `services/run_ops.py` — shared CONFIRMED-run unwind (cancel endpoint + reformulate cascade) and billing-ledger adjustment
- `routes/` — 11 blueprints: `customers.py`, `formulas.py`, `supplies.py`, `pilot_cells.py`, `trials.py`, `letters.py`, `kettle_lines.py`, `components.py`, `runs.py`, `holds.py`, `labels.py`

## Endpoints

All 43 from the scaffold endpoint table, under `/copack`.

## State machines implemented (6)

Formula (DRAFT→IN_TRIAL→TRIAL_PASSED→APPROVED with ACID auto-approval, fail/cancel revision loop, reformulate reset with revision bump), ScaleUpTrial (SCHEDULED→PASSED/FAILED/CANCELLED), ProcessAuthorityLetter (SUBMITTED→ACTIVE→SUPERSEDED with single-active invariant), LabelApproval (DRAFT→SUBMITTED→APPROVED/REJECTED), ProductionRun (8 states incl. CONFIRMED→COMPLETED/ON_HOLD auto-hold fork, ON_HOLD→REWORK re-complete loop, DESTROYED with sibling-hold sweep + final-charge refund), QualityHold (OPEN→DISPOSITIONED with RELEASE/REWORK/DESTROY divergent effects).

## Calculations implemented

- Dual-variant run charge (estimate from planned units, final from actuals): `units_billed = max(units, min_run_units)`, base + locked changeover fee + per-line `Decimal` round-half-up ingredient lines (COPACKER_SUPPLIED only, on units_billed) + packaging lines (planned for estimate, actual for final); billing always moves by delta vs previously applied charge
- Changeover fee: predecessor = latest `scheduled_end ≤ run.start` among occupiers (tie-break latest `created_at`), 75000 on allergen-class switch else 15000
- Kettle-line interval rule: occupancy states `{CONFIRMED, COMPLETED, ON_HOLD, REWORK, RELEASED}`, 4h/1h allergen-conditional gap, `gap < required` conflicts (exactly-equal passes), intersection always conflicts
- Pilot-cell rule: half-open touch-allowed overlap, SCHEDULED only
- Hold metrics: `letter_deviation`/`statutory_margin` at 2dp half-up; pH deviation strict `>`, aw deviation `>=`; ceilings 4.6/0.85; null without ACTIVE letter or for non-deviation reasons
- Boundary-strict thresholds: packaging shortage only when `required > available`, credit breach only when `outstanding + estimate > limit`

## Decisions worth noting

- **Validation pipeline** follows PRD §2.7 order strictly: auth → role → ownership → path/body FK existence → shape → state → statutory (process limits / destroy gate) → domain constraints → letter revision → credit last.
- **Disposition ordering**: statutory gate evaluated before owner routing before segregation of duties; null `statutory_margin` (no ACTIVE letter) fails the RELEASE/REWORK gate per the "strictly positive" prose.
- **REWORK disposition is unconditional** (scaffold precondition list is empty) — it moves the run even with sibling OPEN holds, unlike RELEASE which requires none remaining.
- **Reservation release on first complete only**, detected via prior status `CONFIRMED` vs `REWORK` (no extra flag); on_hand consumed on every complete.
- **Cascades touch every mutated resource** (own `updated_at` + `version`), and the customer record is bumped once per request when billing moves.
- **OCC ordering**: state gate first, then `expected_formula_version`/`expected_component_version` (412); for components, OCC before the `on_hand >= reserved` floor.
- Wall-clock UTC timestamps (task deliberately has no logical-clock endpoint); created_at sort uses a monotonic sequence tiebreak.

Verified with two smoke suites (120 assertions total): full happy path, all error gates, rework billing deltas, reformulate cascade over CONFIRMED runs, and a cold `bash start.sh` reboot confirming an empty store.

## Step 7: Run Tests and Iterate — 2026-08-14T19:45:00.000Z

## Summary

**Result: All 8 parallel rounds pass 68/68.** Exit condition met.

**Iterations run:** 3 sweeps (24 total test rounds).

**Tests deleted:** none. Every failing test traced to verbatim PRD coverage; both fixes were test-artifact bugs, not PRD-silence cases.

**Fixes applied to `test_helpers/` (1):**
- `test_helpers/factories.py` — `create_packaging_component_payload`: added the missing `"COMPONENT_INITIAL_ON_HAND": 100_000` key to the `DEFAULTS` dict. The factory referenced `DEFAULTS["COMPONENT_INITIAL_ON_HAND"]` but the key only existed in `constants.py::TEST_DEFAULTS`, so every packaging-component creation raised `KeyError` before any request reached the server. This single factory bug accounted for all 28 failures in sweep 1 (TRIAGE HINT confirmed: ≥5 failures sharing one setup error → test_helpers was the first suspect). The default value 100_000 matches what downstream assertions already expect (PRD §3.4 declares `initial_on_hand_units` as the seed field).

**Fixes applied to `test_suite/` (1):**
- `test_suite/test_06_quality_holds_and_disposition.py` — added `validate_success` to the `test_helpers` import list. Seven tests (TestReworkCycle ×2, TestDestroyCascade ×2, TestDispositionRouting ×2, TestHoldStateGates::test_disposition_twice_rejected) called `validate_success(resp, 200)` but only `validate_error` was imported → `NameError` in all 8 rounds of sweep 2.

**Fixes applied to `implementation/`:** none. The implementation was PRD-faithful throughout — once the two test-artifact bugs were fixed, all remaining behavior (statutory gate precedence, rework re-completion math, destroy cascade with billing reversal, owner routing, segregation of duties, per-line round-half-up charge math, allergen changeover fees) verified clean with zero implementation changes.

**Progression:** sweep 1 → 40/68 (28 KeyError cluster), sweep 2 → 61/68 (7 NameError cluster), sweep 3 → 68/68 in all 8 rounds, zero flakes.

## Step 8: Finalize PRD — 2026-08-14T19:55:00.000Z

`/home/ubuntu/github/CodingPRD/tasks/task_1815_sauce_condiment_co_packing/workspace/PRD_FINALIZED.md` is produced — a one-phrase patch of PRD.md.

## Line counts

- `PRD.md`: 301 lines; `PRD_FINALIZED.md`: 301 lines. Delta: 0 lines (0.0%); the only change is a 3-word insert within existing line 152.

## Changes (one edit total)

- **§3.4 (Production Resources and Run Planning)** — insert — added the numeric domain "of zero or more" to `initial_on_hand_units` in the component-creation sentence ("…and an `initial_on_hand_units` of zero or more that seeds physical stock") — `implementation/routes/components.py:43-45` (rejects negative values with `ERR_INVALID_REQUEST`/400, accepts zero; the field is required via `req()`).

## Why the other step_7_diff items required no PRD change

- **`test_helpers/factories.py` (COMPONENT_INITIAL_ON_HAND = 100_000)** — pure fixture bug: the factory referenced a key missing from its own `DEFAULTS` dict and crashed with `KeyError` before any request reached the server. The value 100_000 is test-chosen payload data matching `constants.py::TEST_DEFAULTS`; the implementation pins no default (the field is client-supplied and required, which PRD §3.4's creation-field list plus §2.7 stage 5 already determine). The only genuine PRD silence at this fix's subject site was the field's numeric floor — that is the one edit above.
- **`test_suite/test_06_quality_holds_and_disposition.py` (missing `validate_success` import)** — purely mechanical `NameError` in test code with zero behavioral content. I read `implementation/routes/holds.py` end-to-end: every behavior the seven unblocked tests exercise (statutory gate evaluated before actor checks at holds.py:142-145, owner routing at 147-152, segregation of duties at 153-154, `ERR_HOLD_NOT_OPEN` on re-disposition at 137-138, RELEASE sibling-hold check at 160-168, REWORK transition at 169-172, DESTROY cascade sweeping sibling OPEN holds and reversing `final_charge_cents` at 174-185) is already covered verbatim by PRD §2.7 stage 7 and §3.7.
- **No implementation fixes and no test deletions** were listed in the diff, so no further trace sites exist.

## Per-edit pre-edit search log (NO-NEW-MISMATCH rule)

**Edit 1 — `initial_on_hand_units` domain floor (§3.4)**

- **(a) Subject:** the validity domain of the `initial_on_hand_units` input field on `POST /copack/packaging-components` (impl accepts 0, rejects negatives with `ERR_INVALID_REQUEST`/400; PRD stated no floor, while §2.7 stage 5's "quantities must be strictly positive where required" actively invited a wrong strict-positive guess that would reject 0).
- **(b) Paths enumerated and grepped:** `grep -rn "initial_on_hand" implementation/` → only `routes/components.py:43` (required-field read), `:44-45` (`< 0` → `ERR_INVALID_REQUEST` 400), `:50` (seeds `on_hand_units`); `grep` for `STORE.components[` record creation → only `components.py:53`; `services/run_ops.py:19-20`, `routes/runs.py:173/196/223/241`, `services/calc.py:71` touch only `on_hand_units`/`reserved_units`/`unit_cost_cents` on existing records and never read `initial_on_hand_units`; the PUT adjust path (`components.py:69-78`) validates the distinct `on_hand_units` field, whose non-negativity is already implied by the PRD-documented stock floor (`on_hand_units` ≥ `reserved_units`, and `reserved_units` is never negative). Creation is the sole path referencing the field.
- **(c) Wording adjustment:** chose "of zero or more" to mirror the sibling phrase "a `unit_cost_cents` of zero or more" in the same sentence and the PRD's established inline-domain convention ("of at least one", "zero or more"), under which §2.7 stage 5 maps any violation to `ERR_INVALID_REQUEST` — exactly matching impl behavior (0 accepted, negative → 400) with no other enumerated path affected.

## Step 9: Complete PRD — 2026-08-14T20:10:00.000Z

The diff confirms all 21 hunks applied cleanly. Task complete.

## Summary

**Produced:** `/home/ubuntu/github/CodingPRD/tasks/task_1815_sauce_condiment_co_packing/workspace/PRD_COMPLETED.md`

**Source vs output:** `PRD_FINALIZED.md` (301 lines, 45,169 chars) → `PRD_COMPLETED.md` (304 lines, 47,950 chars); char-delta **+2,781**.

**Counts:** 17 ambiguity-pins, 4 mismatch-revisions (21 changes total).

**Changes:**

- §2.2 — insert — ambiguity — undeclared `/copack` path → 404 `ERR_NOT_FOUND`, unsupported method → 405 `ERR_INVALID_REQUEST`, same envelope — `implementation/app.py:24-30`
- §5 — insert — ambiguity — `ERR_NOT_FOUND` catalogue row (index companion to the §2.2 pin) — `implementation/errors.py:56`
- §2.3 — insert — ambiguity — non-integer `limit`/`offset` → `ERR_INVALID_REQUEST`; out-of-range integers clamped (limit to [1,100], offset to 0), never rejected — `implementation/response.py:53-74`
- §2.4 — revise — ambiguity — `version` starts at 1 on creation — `implementation/services/core.py:20`
- §2.5 — insert — ambiguity — pipeline position of the OCC check: after shape validation and the endpoint's state gate, ahead of domain constraints (formula update: after the `DRAFT` gate; stock adjustment: before the stock floor) — `implementation/routes/formulas.py:126-130`, `implementation/routes/components.py:72-78`
- §2.7 stage 5 — revise — ambiguity — strings must be non-empty — `implementation/util.py:65-68`
- §2.6 — revise — **mismatch** — blanket "all monetary values are integer cents" narrowed: a supply's `unit_cost_cents` is the lone exception, accepted as a plain JSON number — `implementation/routes/supplies.py:51` (uses `as_num`, unlike `as_int` at `components.py:40`/`formulas.py:51`)
- §3.1 — insert — ambiguity — supply cost validation detail: non-negative number (fractional OK) for `COPACKER_SUPPLIED`; any number (even negative) merely stored for `CUSTOMER_SUPPLIED` — `implementation/routes/supplies.py:50-57`
- §3.1 — insert — ambiguity — receipt `quantity` is a decimal preserved as submitted — `implementation/routes/supplies.py:106-108`
- §3.1 — insert — ambiguity — a spec field present with JSON `null` is treated as omitted on formula update — `implementation/routes/formulas.py:103-124`
- §3.2 — insert — ambiguity — `scheduled_start`/`scheduled_end` parsing: ISO-8601, date-only → midnight UTC, offsets normalized, naive → UTC, unparseable → `ERR_INVALID_REQUEST` — `implementation/util.py:10-30`
- §3.2 — revise — ambiguity — `yield_units` is an integer — `implementation/routes/trials.py:100-102`
- §3.2 — insert — ambiguity — a failing trial records `yield_units` too — `implementation/routes/trials.py:114-116`
- §3.4 — insert — ambiguity — each `packaging_requirements` line's `quantity_per_unit` is strictly positive — `implementation/routes/runs.py:62-64`
- §3.4 — revise — **mismatch** — "Until confirmation, `changeover_fee_cents` … carry no value" replaced: the fee is first written by a confirmation *attempt*, the estimate only by a successful one — `implementation/routes/runs.py:185-193`
- §3.5 — revise — **mismatch** — estimate packaging lines extend against `planned_units`, not "the units billed" (diverges when planned < `min_run_units`) — `implementation/services/calc.py:67-74,78-80`
- §3.5 — revise — **mismatch** — "computed once at confirmation and locked": fee is written before the credit gate, persists on a credit-rejected confirmation (run stays `PLANNED`, version/estimate untouched), and is recomputed on retry; never recomputed once `CONFIRMED` — `implementation/routes/runs.py:185-193`
- §3.6 — insert — ambiguity — billing delta applied on every completion; a zero delta still advances the customer's `version` — `implementation/routes/runs.py:237`, `implementation/services/run_ops.py:9-13`
- §3.7 — insert — ambiguity — either measurement may accompany any hold reason category and is stored verbatim; mandatory only for its deviation category — `implementation/routes/holds.py:52-61`
- §3.7 — revise — ambiguity — placing a hold on an already-`ON_HOLD` run leaves the run's `version` untouched — `implementation/routes/holds.py:86-88`
- §3.7 — revise — ambiguity — `DESTROY` also fires from `REWORK` (sibling-hold case); `RELEASE`/`REWORK` dispositions are no-ops on the run once a sibling has moved it out of `ON_HOLD` — `implementation/routes/holds.py:160-185`

**Key finding:** the one substantive behavioral mismatch was the estimate's packaging lines — PRD said "multiplied by the units billed" but `compute_estimate` passes `planned_units` for packaging, so the two diverge whenever `planned_units < min_run_units`. Everything else was pinning silent edge behavior (validation types, clamping, OCC ordering, fee persistence across a failed credit gate, disposition status guards). Tests were used only as cross-reference; no test-derived behavior was adopted over impl.
