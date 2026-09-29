# Worklog — task_2472_employer_tuition_benefit_administration

## Step 1: Create task directory — 2026-09-02T21:26:02.142Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2472_employer_tuition_benefit_administration` and its `workspace/` subdirectory. Index 2472 was pre-assigned by the orchestrating caller; no scan of `./tasks/` was performed and no other task directory was created.

## Step 2: Generate scaffold — 2026-09-02T22:38:54.727Z

Chunk 3 appended and the artifact set is complete and lint-clean.

**Files** (all in `/home/ubuntu/github/CodingPRD/tasks/task_2472_employer_tuition_benefit_administration/`):
- `SCAFFOLD.yaml` — §1.0–§1.7
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — sole key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` — sole key `scaffold_corner_design`

**Lint verdict** (`python3 skills/prd-bench-scaffold-generator/scaffold_lint.py <task dir>`):
```
Coverage
  §1.5 endpoints declared:    51
  §1.1 entities declared:     15
  §1.8 instances scanned:     18
  §1.9 instances scanned:     47
  Calls scanned (§1.8+§1.9):  781

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
(The linter counts only recipe-bearing instances; the corner file has 60 instances in total, 13 of which are `excluded_because` stubs.)

**Counts**
- §1.0–§1.7: 15 entities, 8 state machines, 2 `concurrency_rules`, 8 calculations, 44 validations (priority-ordered), 51 endpoints, 43 errors, 5 roles.
- §1.8: 9 rule blocks × 2 instances = 18 instances, all nine §0.5 `rule_id`s.
- §1.9: 9 sections, 60 instances (47 with `test_recipe`, 13 `excluded_because` stubs) — entities 9, state_machines 8, calculations 9, validations 6, endpoints 6, errors 11, rbac 4, cross_cutting_complexity_layers 5, consistency_model 2.

**Chunk-3 content added**: `errors` (11 — including a 12-entity NOT_FOUND sweep and three lifecycle-lockdown bundles), `rbac` (4 — exclusive-op denial, employer-vs-employer peer isolation, one endpoint under four roles incl. the opaque Coach, missing/unknown role header → 401), `cross_cutting_complexity_layers` (2 real OCC instances mapping both §1.2.1 `concurrency_rules`, plus 3 stubs), `consistency_model` (2 immediate-visibility instances, one single-field and one multi-entity cascade).

**Verification done**: all 43 catalog errors are now provably triggerable (`uncovered: []`); instance names unique across §1.8 ∪ §1.9; every stub cites a real §1.8 instance and carries no `test_recipe`.

**Two scaffold defects found and fixed while validating**
1. `ERR_REIMBURSEMENT_NOT_ALLOWED` (priority 31) was unreachable — priority 24's funding-state guard always masked it. Priority 24's `check` now stands aside for `DIRECT_BILL` enrollments.
2. Earlier in the session, `input:` flow sequences containing `foo?` optional markers and `$.data[...]` capture values broke `yaml.safe_load`; both are now quoted throughout.

Also corrected in the new text after checking §1.5/§1.3: `POST /repayment-obligations/{id}/waive` takes `input: []` (payload `{}`, waives the whole balance) and a waiver deliberately does **not** release `cap_clawback_hold_cents`; and the settled 4-credit reimbursement chain yields `approved_amount_cents` 96000 with a 4800 tier-1 admin fee (not 80000/4000).

## Step 3: Copy shared files — 2026-09-02T22:38:54.727Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-02T22:49:16.356Z

PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_2472_employer_tuition_benefit_administration/workspace/PRD.md`.

**Document:** 412 lines, ends cleanly at the completed §5 Error Code Catalogue table (98 total table rows = 51 endpoints + 43 errors + 4 header/separator rows).

**Structure (domain-derived, not copied from the example):**
- §1 Introduction — 3 paragraphs (benefit administration, tax-compliance ledger, advising/reporting angles)
- §2 — 10 subsections: 2.1 RBAC · 2.2 Response Structure (verbatim from `section-2.2-response-structure.md`, byte-identical) · 2.3 Pagination · 2.4 Common Properties + Logical Clock · 2.5 Money/Rounding · 2.6 Annual Cap as Conserved Pool · 2.7 Version Pinning & OCC · 2.8 Cascade Discipline · 2.9 Validation Ordering (all 44 rules in priority order with error IDs and full `applies_to` path enumerations) · 2.10 Educational-Assistance Tax Ledger
- §3 — 9 subsections: employer/policy/eligibility · schools/programs/agreements · catalog curation + non-catalog exception cycle · enrolling & cap reservation · registration/direct-bill · outcomes/reimbursement · withdrawal/clawback/repayment · coaching & persistence risk · term-close/true-up/utilization report
- §4 endpoint table (4 columns) · §5 error table (2 columns)

**Hard Contract Reports (all verified mechanically):**

```
Field coverage check:
- entities[].fields: 112 required, 112 present, 0 missing
- endpoints[].input (request body): 64 required, 64 present, 0 missing
- endpoints[].query_params: 22 required, 22 present, 0 missing
- endpoints[].output shape identifiers (utilization report, term-close counters, clock): all present, 0 missing
- state enumeration values (8 machines): 0 missing · enum-field values: 0 missing · errors[].id: 43/43 present
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 44 checked, 44 expressed in prose (absolute ordering stated in §2.9), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected_<parent>_version + error_id + 412 all named), 0 missing
- state_machines[].transitions: 8 machines / 33 transitions checked, 33 fully expressed with preconditions↔error_id and every side effect, 0 missing
- calculations[]: 7 checked (incl. 3 dual/triple-variant families), 7 fully expressed with pinned evaluation order, constants embedded in business units, 0 missing
- validations[] conditions: 44 checked, 44 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 51 endpoints checked, all cascades and scope enumerations expressed, 0 missing
- entities[].fields[] structured content: 112 checked (types, defaults, initial values, enum sets), reconstructible from prose, 0 missing
- sibling-branch symmetry: 6 groups checked (3-way approval decide, 2-way claim decide, DIRECT_BILL/REIMBURSEMENT confirm fork, partial/full repayment, payment-vs-waive cap treatment, drop-window/post-window withdraw), 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 890
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

No fuzzy/approximating words present (grep for approximat/roughly/conservativ/etc. returns nothing). Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, and no sibling task directory was read.

**Orchestrator truncation guard:** verified independently — `tail -25` shows the §5 table completing with `ERR_ANNUAL_CAP_EXCEEDED`, and the heading scan shows §1→§5 all present with §3 carrying all nine subsections. No truncation; no regeneration needed.

## Step 5: Generate unit tests — 2026-09-03T00:46:01.108853494Z

All 82 tests are in place and every audit is green. Final state:

**Stage 1 — `test_helpers/`**
`__init__.py`, `constants.py`, `types.py`, `api_errors.py` (43 error IDs + `ERROR_HTTP_STATUS`, registered via `set_error_http_status_map` at import), `api_client.py` (`TuitionBenefitApiClient`, 51 endpoint methods), `test_users.py`, `assertions.py` (19 domain assertions: conserved cap pool, obligation identity, per-row/per-year tax ledger identities, persistence banding, term-close counts), `factories.py`, `fixtures.py` (`Scenario` + 33 named builders across 9 employer chains).

**Stage 2 — `test_suite/`** (`conftest.py` + 15 test modules, 82 tests)
- Queue B (breadth, 46 tests): test_01_resource_shapes_and_defaults.py (9), test_02_lifecycle_transitions.py (6), test_03_money_and_risk_calculations.py (5), test_04_precondition_validations.py (4), test_05_endpoint_behaviours.py (4), test_06_error_surface.py (10), test_07_role_and_ownership_scope.py (4), test_08_concurrency_and_immediacy.py (4)
- Queue A (depth, 36 tests, 2 per instance): test_09_dual_variant_awards.py (4), test_10_formula_composition.py (4), test_11_state_machine_shapes.py (4), test_12_cascade_chains.py (4), test_13_priority_and_boundaries.py (8), test_14_cross_entity_and_temporal.py (8), test_15_conserved_invariants.py (4)

**Coverage audit**: all 18 difficulty instances have exactly 2 tagged tests; 46 of the 47 non-stub corner instances have >=1 tagged test (13 `excluded_because` stubs correctly untranslated). Every `Design:` tag resolves to a real `name:` in its source yaml; every test has exactly one tag, as the docstring's last line. `check_quotes` reports `problems: 0` (every docstring quote is greppable verbatim in `workspace/PRD.md`); `pyflakes` clean on the suite and on fixtures/types/factories/assertions/api_client; `pytest --collect-only` collects 82; no `skip`/`skipif`/`xfail`, no "scaffold" mentions.

**Instances skipped (1)**
- `Corner/errors/settled_reimbursement_chain_locks_repeat_operations` — fails the uniquely-derives filter. The design asserts `ERR_CLAIM_INVALID_STATE`, but PRD §2.9's absolute ordering puts priority 24 (`ERR_ENROLLMENT_INVALID_FUNDING_STATE`) ahead of priority 26, so the PRD uniquely derives a different error for that request. Left as a gap.

**Design-vs-PRD substitutions made while translating (worth recording)**
1. `Difficulty/combinatorial_formula/admin_fee_tier_keyed_on_pre_settlement_employer_disbursement` — the Summit recipe's policy window [2026-01-01, 2027-01-01) would leave no current policy at the recipe's own 2027-03-25 clock (§2.9 rule 28), and its agreement window ending 2026-12-31 conflicts with §3.2's closed-window requirement for the 2027-04-01 term start. `build_summit_base` uses policy `effective_to` 2028-01-01 and agreement `effective_to` 2027-12-31; every asserted figure is preserved (rates 499,000/32,802/40,000; 4,990,000 pre-state; 68,884 @ 3,444; 48,000 @ 1,920; employer 5,106,884/5,364).
2. `Difficulty/non_linear_state_machine/enrollment_academic_and_funding_axes_advance_independently` — the second term was unspecified; a 2027 term start would push `plan_year` out of the employee's `cap_plan_year` scope (§2.6) and make the cap-bucket assertions unassertable. Chose term "2026-WI" [2026-12-16, 2027-03-31] with clock 2026-12-20.
3. `Difficulty/boundary_precision_check/section_127_exclusion_limit_at_limit_versus_first_cent_beyond` — the design's asserted `cap_available_cents` 422,500 at the at-limit observation only holds once the second enrollment exists and is BILLED, so both tests use `build_beacon_second_term_billed`.
4. `Corner/calculations/persistence_risk_score_components_combine_with_flag_cap` — design used two risk-flag names absent from the PRD enum and session dates after the pinned clock; translated with PRD-declared flags and in-window dates.
5. `Corner/errors/unknown_path_ids_raise_each_entity_specific_not_found` — restricted to PRD-declared endpoints.
6. `Corner/consistency_model/agreement_termination_cascade_is_visible_immediately` — the design's SYSTEM-outcome sub-assertion is not derivable from the PRD and was omitted; the rest of the cascade is asserted.

The suite is not executed here (that requires an implementation under `workspace/implementation/`, which I did not read or create).

## Step 6: Generate implementation — 2026-09-03T00:46:01.108853494Z

Implementation complete and verified.

**Files created (18 files, 3,215 lines; 3,204 Python LOC)** under `workspace/implementation/`: `start.sh` (8 — guarded `pip install` + `exec python3 app.py`, foreground, honors `$PORT`, default 10000), `requirements.txt` (1), `app.py` (63 — app factory, error handlers, `before_request` derived-state refresh), `store.py` (119 — in-memory `Store` of 15 dicts, logical clock, id/seq generation, per-request-idempotent `touch()`), `errors.py` (65 — 42-code catalog + status mapping), `envelope.py` (47), `validate.py` (263), `auth.py` (56 — header auth, 5 roles, entity-backed ownership scopes), `domain.py` (755 — 7 calculations, cap-pool conservation, tax ledger, all cascades, term-close helpers), `serialize.py` (285), `routes/` (8 files, 1,561 — all 51 endpoints).

**Verification results**
- Route registration: exactly 51 routes, one per declared SCAFFOLD endpoint (diffed path-by-path).
- Boot verification (real process, `PORT=18477 bash start.sh`): clean boot; `GET /catalog-listings?limit=5` → 200 `total_count: 0`; `GET /partner-agreements` → 200; `GET /tax-ledger-entries` → 200; `POST /employers` → 201. `GET /enrollments` correctly 403 for `PlatformAdmin` (role not in that endpoint's declared list). Store empty on boot — no seeded/preloaded data. Process killed cleanly.
- No disk persistence: grep for sqlite/open(/json.dump/pickle//tmp across all Python files returns nothing.
- Functional smoke tests (throwaway, not deliverables) exercised both money paths end to end and passed — REIMBURSEMENT (policy activate → eligible employee → agreement → listing rate 42500 from 50000 @ 15% → enrollment gross 255000/reserve 204000 → coaching session → PASSED @ 3.7 → claim approve 229500 with 0.10 grade bonus, fee 11475 @ 5% → roll-ups → utilization report → termination → EARLY_DEPARTURE obligation → partial payment → waive → term-close) and DIRECT_BILL (invoice ISSUED due term_start+30d → approve-payment → pay → SETTLED with cap/tax ledger updated; in-drop-window withdrawal → RELEASED + invoice VOIDED + SYSTEM WITHDRAWN outcome; full approval-request cycle submit → review → REQUEST_CHANGES → resubmit → review → APPROVE materialising the `APPROVED_EXCEPTION` listing at list rate with [REIMBURSEMENT] and null `agreement_id`; listing suspend; agreement terminate cascade).
- Cap-pool invariant `annual_cap == available + reserved + disbursed + clawback_hold` held after every mutation.
- Error surfaces confirmed with declared codes/statuses across 401/403/404/412/409/422/400.

**Notes**
- Isolation constraint honored: nothing under `test_helpers/`, `test_suite/`, `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`, or any sibling task directory was read. Every decision traces to `INSTRUCTION.md`, `SCAFFOLD.yaml`, or `PRD.md`.
- Two judgement calls flagged: (1) `GET /tax-ledger-entries/{id}` with an unknown id returns 404 `ERR_NOT_FOUND` because the catalog has no tax-entry not-found code; (2) undeclared path/method combinations return `ERR_NOT_FOUND` at 404/405.

**Orchestrator note on Step 5/6 isolation:** the skill prescribes launching Steps 5 and 6 concurrently in one message, which also gives physical isolation (impl-gen starts before `test_suite/` exists). I issued them sequentially, so `test_suite/` and `test_helpers/` were already on disk when Step 6 started. I compensated by adding an explicit hard prohibition on reading `test_helpers/`, `test_suite/`, and both design YAMLs to the Step 6 prompt, and the Step 6 agent confirmed it read none of them. Isolation was enforced by instruction rather than by absence; noting it here for auditability.

## Step 7: Run tests and iterate — 2026-09-03T01:15:00.000Z

All 8 rounds of a single sweep passed 82/82. Here is the report.

**Iterations run:** 3 sweeps (8 parallel rounds each, `per-test-server`, no early exit).

- **Sweep 1** — 81/82 in all 8 rounds; one deterministic failure: `test_agreement_activation_is_refused_for_an_unaccredited_school`.
- **Sweep 2** — 81/82 in all 8 rounds; the accreditation test was fixed, but a *new* failure appeared: `test_each_settlement_pushes_the_next_one_toward_a_cheaper_tier`, failing with `ConnectionResetError` / `RemoteDisconnected` / `IncompleteRead` — i.e. the server process vanished mid-request, not an assertion trip. All 8 rounds' servers died at the same wall-clock instant (00:59:03), and the host has other pipelines running identically-named `python3 app.py` servers, so a neighbouring pipeline's broad `pkill` is the plausible cause. Verified it was not a real defect by booting the server manually and running the test in isolation: **passed**. No code change made.
- **Sweep 3** (launched 01:09:08, results written 01:11:4x) — **all 8 rounds 82/82 passed, 0 failed, 0 errors**, ~153s per round. All eight `results.${i}.json` files read and verified.

**Tests deleted:** none. No test failed STEP 1a (PRD coverage) or STEP 1b (unique derivability).

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `test_suite/`:**
- `test_suite/test_04_precondition_validations.py`, `test_agreement_activation_is_refused_for_an_unaccredited_school` — STEP 2 test bug in the setup chain. The test registered the second (PROBATION) school with `Scenario.register_school(primary=False, ...)`, which by design does *not* update `s.school_id`; the test then read `probation_school_id = s.school_id`, which still held the **UNACCREDITED** school's id. The "should be allowed" agreement was therefore drafted against the unaccredited school, and the PRD-faithful implementation correctly returned `ERR_SCHOOL_NOT_ACCREDITED` (422) where the test expected 200. Fixed by capturing the returned record: `probation_school = s.register_school(primary=False, ...)` / `probation_school_id = probation_school["id"]`. This makes the test faithful to PRD §3.2 ("A school on `PROBATION` may be activated"); the `ERR_SCHOOL_NOT_ACCREDITED` assertion on the genuinely unaccredited school was left exactly as-is.

**Fixes applied to `implementation/`:** none. No implementation defect was found — the single real bug in the artifact was the fixture-identity mix-up above.

Files touched (absolute):
- `/home/ubuntu/github/CodingPRD/tasks/task_2472_employer_tuition_benefit_administration/test_suite/test_04_precondition_validations.py`

**Orchestrator independent verification of the final sweep** (per standing guidance not to accept a clean-sweep claim without checking the artifacts): all 8 `workspace/implementation/results.{1..8}.json` exist, each ~24.6 KB, all mtimes within one second at 2026-09-03T01:11:4x, and each parses to `{passed: 82, failed: 0, total: 82, errors: 0, skipped: 0}`. Sweep confirmed genuine.

**Step 8 skip decision:** NOT skipped. Step 7 applied 1 `test_suite/` fix, so the run was not a zero-iteration baseline pass. Note the fix was a pure fixture/identity bug with 0 `implementation/` fixes and 0 deletions, so Step 8 is expected to find little or nothing to pin — that is a legitimate outcome, and Step 9's full scan remains the substantive completeness pass.

## Step 8: Finalize PRD — 2026-09-03T01:17:05.147462726Z

## Result: `PRD_FINALIZED.md` is a byte-identical copy of `PRD.md` — zero edits warranted

**Line counts:** PRD.md 412 → PRD_FINALIZED.md 412 lines, **0.0% delta** (md5 identical: `d8cf4215ea2ba15d112730c0fb43cf29`).

**Changes:** none.

### Analysis of each `<step_7_diff>` item

**Item 1 — `test_suite/test_04_precondition_validations.py::test_agreement_activation_is_refused_for_an_unaccredited_school` (test-side fixture-identity fix).**

Subject: the accreditation gate on `POST /partner-agreements/{id}/activate`.

Impl paths enumerated (grepped `ACCREDIT` across all of `implementation/`, 8 hits total, all inspected):
- `implementation/routes/schools.py:157-172` — `activate_agreement`: `must(agreement)` → `employer_scope` → `status != "PENDING"` → `accreditation_status == "UNACCREDITED"` → `fail("ERR_SCHOOL_NOT_ACCREDITED")`. Exactly PRD §3.2 line 209 ("provided the school's `accreditation_status` is not `UNACCREDITED`… A school on `PROBATION` may be activated") and PRD §2.9 rule 34 line 163 ("is not `UNACCREDITED` when activating an agreement"). Check ordering also matches PRD rules 8 → 16 → 20 → 34.
- `implementation/routes/catalog.py:291-297` — the parallel, *stricter* gate on `decide_request`/APPROVE: `!= "ACCREDITED"` → `ERR_SCHOOL_NOT_ACCREDITED`. Exactly PRD §3.3 line 223 ("must be exactly `ACCREDITED`, so a school on `PROBATION` is refused here") and rule 34's first clause.
- `implementation/routes/schools.py:44-53` — school creation: enum `ACCREDITED|PROBATION|UNACCREDITED`, default `ACCREDITED`. Matches PRD §3.2 line 203.
- `implementation/errors.py:46` — 422 status. Matches the §5 catalogue.

No accreditation state is mutable after creation anywhere in the impl (no other write to `accreditation_status`), so no cascade or re-evaluation path exists that PRD would need to describe. **Conclusion: PRD already uniquely determines this rule at two independent places, with the two endpoints' differing strictness (`not UNACCREDITED` vs. `exactly ACCREDITED`) already spelled out.** The Step 7 failure was purely `Scenario.register_school(primary=False, …)` not updating `s.school_id`, so the test drafted the "should be allowed" agreement against the wrong (unaccredited) school. That is a test-helper-usage bug with no PRD surface. Nothing to pin.

**Item 2 — `test_each_settlement_pushes_the_next_one_toward_a_cheaper_tier` (Sweep 2 `ConnectionResetError`).** Step 7 made **no code change**; the diagnosis was a neighbouring pipeline's `pkill` killing the server, confirmed by an isolated re-run passing. A crash with no fix reveals neither PRD silence nor mismatch. As due diligence I still read the fee-tier path — `implementation/domain.py:532-538` (`admin_fee_pct`: `<5,000,000` → tier 1, `<20,000,000` → tier 2, else tier 3) and `implementation/routes/money.py:163-166` (fee basis snapshotted via `employer_total_disbursed()` *before* mutation, fee = `round_half_up(approved * pct)`) — and both match PRD §3.6 line 265 steps three through six verbatim. No edit.

**Item 3 — test deletions, `test_helpers/` fixes, `implementation/` fixes.** All three are "none" in the Step 7 diff, so there is no site to trace an edit to.

### Note on an out-of-scope ambiguity (deliberately not edited)
While enumerating the claim-approval path I observed that PRD §3.6 line 265 first says `employer_settled_cents` is `min(uncapped_final, employer_reserved_cents + cap_available_cents)`, then at the end of the same paragraph says the request "sets both `employer_settled_cents` and `employer_disbursed_cents` to `approved_amount_cents`" — and the impl (`routes/money.py:175-176`) does the latter. This is a pre-existing internal tension in PRD.md, not traceable to any `<step_7_diff>` item, so per the HARD SCOPE rule I left it untouched. Flagging it only so it is not mistaken for something I missed.

**Orchestrator note:** md5 equality of PRD.md and PRD_FINALIZED.md independently confirmed. The zero-edit outcome is consistent with Step 7's shape (0 implementation fixes, 0 deletions, 1 pure fixture-identity fix) — there was no PRD-silence site to pin. The §3.6 `employer_settled_cents` tension Step 8 flagged as out-of-scope IS in scope for Step 9's full impl scan; it is passed to Step 9 as a hint below.

## Step 9: Complete PRD — 2026-09-03T01:27:05.767069632Z

Done. `workspace/PRD_COMPLETED.md` is written.

**Source vs result:** PRD_FINALIZED.md 412 lines / 91,717 chars → PRD_COMPLETED.md 413 lines / 97,474 chars (+1 line, +5,757 chars). 24 in-paragraph revisions plus 1 new bullet in the existing §2.2 bullet list; no new sections.

**Counts:** 18 ambiguity-pins, 7 mismatch-revisions (25 changes).

**KNOWN LEAD — resolved:** `money.py:162-176` computes `reimbursement_final()` only as an intermediate feeding the three-way `min` for `approved_amount_cents`, then sets *both* `employer_settled_cents` and `employer_disbursed_cents` to `approved_amount_cents`. So the *second* half of the PRD paragraph was right and the first half wrong; the first quantity was renamed "the capped final entitlement" with an explicit statement that it is never written onto the enrollment. Both other flagged judgement calls were genuinely unpinned and are now pinned.

**Changes:**

- §2.1 — revise — mismatch — blank/whitespace-only header is treated as absent → `ERR_UNAUTHENTICATED` — auth.py:15
- §2.2 — insert — ambiguity — undeclared path → `ERR_NOT_FOUND` 404, undeclared method → `ERR_NOT_FOUND` 405, unparseable body → `ERR_INVALID_REQUEST` 400, fault → `ERR_INTERNAL` 500 — app.py:38-53
- §2.3 — insert — ambiguity — non-integer pagination and out-of-enum filters are 400; id-valued filters match nothing; undeclared query params ignored — validate.py:232-259, routes/common.py:15
- §2.3 — insert — ambiguity — equal-`created_at` tie broken by server creation sequence — store.py:118
- §2.4 — insert — ambiguity — `to_iso8601` accepts any ISO form, offsets normalized, naive read as UTC; response body is the single field `current_utc` — validate.py:195-208, ops.py:19
- §2.4 — insert — ambiguity — employee clock-derived fields refreshed at the start of every request without moving `updated_at`/`version` — app.py:28-32, domain.py:259
- §2.4 — insert — mismatch — `created_at`/`updated_at`/`api_request_timestamp` come from the host wall clock, not the logical clock — store.py:65, envelope.py:18
- §2.8 — insert — mismatch — `version` moves at most once per request per row; an employee recompute that changes no derived field is not a mutation (exceptions listed) — store.py:86-115, domain.py:266-274
- §2.9 r16 — revise — mismatch — the five collection roots do no ownership check and no ownership filtering — schools.py:140, catalog.py:129/210, enrollments.py:177, money.py:229
- §2.9 r23 — revise — ambiguity — `POST /tuition-invoices/{id}/pay` joins rule 23 with "anything other than `WITHDRAWN`", fixing 23 < 24 < 25 — money.py:54-65
- §3.1 — insert — ambiguity — future `hire_date` yields `tenure_months` 0, not negative — domain.py:198
- §3.1 — insert — ambiguity — patch fields all optional; `termination_date` outside a `TERMINATED` move is 400; a patch to `ACTIVE`/`LEAVE` clears it to null — employers.py:246-263
- §3.2 — revise — mismatch — the agreement coverage window is never tested against an enrollment's `term_start_date` — enrollments.py:53-173 (no such check)
- §3.3 — insert — ambiguity — `decision_note` <= 2,000 chars, null when omitted — catalog.py:279
- §3.3 — insert — ambiguity — the `ELIGIBLE` precondition on approve is `ERR_EMPLOYEE_NOT_ELIGIBLE` (422), checked after accreditation — catalog.py:291-302
- §3.3 — insert — ambiguity — the five admissibility conditions are not in evaluation order; §2.9 puts rule 42 last — catalog.py:175-192
- §3.3 — insert — ambiguity — resubmit leaves `decision_note` untouched — catalog.py:265-271
- §3.4 — insert — ambiguity — omitting `funding_model` under `HYBRID` is `ERR_FUNDING_MODEL_NOT_ALLOWED`, not a 400 — enrollments.py:124-134
- §3.5 — insert — ambiguity — unknown tax-entry id → `ERR_NOT_FOUND` 404 — money.py:244-246
- §3.6 — insert — ambiguity — `term_code` mismatch / `credits_earned` overflow are 400, evaluated after the enrollment resolves and before ownership — enrollments.py:279-284
- §3.6 — insert — ambiguity — a school-posted `WITHDRAWN` outcome moves only the academic axis, touching no money — enrollments.py:315-318
- §3.6 — insert — ambiguity — claim `decision_note` <= 2,000 chars, null when omitted — money.py:133
- §3.6 — revise — mismatch — capped final entitlement is an intermediate; `employer_settled_cents` = `approved_amount_cents` — money.py:162,175-176
- §3.7 — insert — ambiguity — withdrawal past the deadline with money at `RESERVED`/`BILLED` leaves the funding axis and open invoices untouched — enrollments.py:250-254
- §3.7 — revise — mismatch — early-departure clawback is gated on a non-zero unserved remainder (a term ending after `termination_date` clamps to zero elapsed and is clawed back in full), not on `term_end_date` being before it — domain.py:457-463
- §3.9 — insert — ambiguity — `run_annual_true_up` defaults false; definitions of `closed_enrollment_count` and `coaching_hold_employee_count` — ops.py:26-28,66-70
- §3.9 — revise — mismatch — the utilization report carries nine figures beside `plan_year`, not ten — domain.py:690-701

Everything else walked (all 51 endpoints, the §2.9 ordering per route, cap/tax ledger arithmetic, persistence scoring, all four cascades, term-close, the serializer field sets) already matched the PRD uniquely. Notably the §2.9 rule order is honored exactly by every route, and the money formulas in §3.4/§3.5/§3.7 need no change.

**Orchestrator verification:** `PRD_COMPLETED.md` is 413 lines, contains all five top-level sections (§1–§5) and 27 headings total, and ends at the completed §5 error table (`ERR_ANNUAL_CAP_EXCEEDED`) — not truncated.

## Pipeline complete — 2026-09-03T01:27:05.767069632Z

All nine steps finished. Final state: 15 entities / 51 endpoints / 43 errors scaffolded; PRD.md 412 lines; 82 tests across 15 modules in `test_suite/` (0 deleted, 0 skipped, 0 xfail); implementation 18 files / ~3,200 LOC; final 8-round parallel sweep 82/82 in every round (`results.{1..8}.json` retained); `PRD_FINALIZED.md` byte-identical to `PRD.md`; `PRD_COMPLETED.md` written with 25 alignment edits.
