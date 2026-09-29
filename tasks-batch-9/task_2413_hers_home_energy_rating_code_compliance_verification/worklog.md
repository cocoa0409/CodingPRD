# Worklog — task_2413_hers_home_energy_rating_code_compliance_verification

## Step 1: Create task directory — 2026-09-02T15:37:16.250Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2413_hers_home_energy_rating_code_compliance_verification` and its `workspace/` subdirectory. Index 2413 was pre-assigned by the orchestrating pipeline; no scan of `./tasks/` was performed and no other task directory was created.

## Step 2: Generate scaffold — 2026-09-02T17:02:25.546Z

All three scaffold artifacts for task 2413 are complete and lint-clean. The hard constraint was honored throughout: nothing under `tasks/` other than this task's own directory was listed, globbed, grepped or read — the design comes only from the scenario line plus the scaffold-generator skill's own spec/references.

## Files
- `/home/ubuntu/github/CodingPRD/tasks/task_2413_hers_home_energy_rating_code_compliance_verification/SCAFFOLD.yaml` (§1.0–§1.7, no design keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_2413_hers_home_energy_rating_code_compliance_verification/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single key `scaffold_difficulty_design`)
- `/home/ubuntu/github/CodingPRD/tasks/task_2413_hers_home_energy_rating_code_compliance_verification/SCAFFOLD_CORNER_DESIGN.yaml` (single key `scaffold_corner_design`)

## Contents
- **Entities (12):** Builder, Subdivision, PlanModel, Home, Rater, Rating, Inspection, DiagnosticTest, SampleSet, QAReview, CorrectiveAction, DocumentPackage.
- **Endpoints:** 44 (incl. `POST /_clock/set_current_utc`; logical clock default `2026-08-01T00:00:00Z`).
- **State machines:** 7 (Rating has parallel dimensions stage / compliance_status / qa_status; SampleSet, Inspection, QAReview, CorrectiveAction, DocumentPackage, Rater).
- **Calculations:** 10 (hers_index, blower-door/duct normalization, compliance_path_selection waterfall, sample_tested_home_selection, sample_set_representative_index, qa_sampling_quota, incentive_amount with PROVISIONAL/CERTIFIED variants, builder_incentive_ledger, home_coverage_ledger).
- **Validations:** 35 priority-ordered rules; **errors:** 44 codes.
- **§1.8 difficulty design:** 9 rule_ids, 19 instances.
- **§1.9 corner design:** 74 instances across all 9 sections — entities 11, state_machines 14, calculations 14, validations 21, endpoints 3, errors 2, rbac 3, cross_cutting_layers 5, consistency_model 1. 56 carry full `test_recipe`s; 18 are `excluded_because:` stubs citing §1.8 instances by name (all citations resolve, no name collides across the two design files).
- Error-catalog audit: every code except the `ERR_XXX` envelope placeholder is triggered by at least one instance.

## Lint
```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
(44 endpoints, 12 entities, 19 §1.8 + 56 §1.9 instances, 880 calls scanned.)

## Design adjudications
1. **File lock scope.** Priority 9 `ERR_RATING_FILE_LOCKED` is deliberately *not* applied to the document-package endpoints, so tax-credit/utility packages remain draftable and issuable on a REGISTERED, locked file (verified against the `DRAFT_to_ISSUED` precondition `Rating.stage IN {CONFIRMED, REGISTERED}`).
2. **Reaching `ERR_REPRESENTED_HOME_NOT_TESTABLE`.** `individual_testing_required` is computed and only set by cascade A/B, both of which suspend the builder, and there is no builder-reinstate endpoint. Because priority 26 guards `POST /sample-sets` and `/select` but not `/homes`, the September sample set is created *before* the cascade and the flagged home added afterwards — proving 18 fires ahead of 23 and 24.
3. **SampleSet OCC re-reads.** `POST /sample-sets/{id}/homes` returns Home, not SampleSet, so every multi-add recipe re-reads `GET /sample-sets/{id}` for the next `expected_sample_set_version`; the stale-version instance asserts member_count stays 1 until the refreshed version is supplied.
4. **FAIL_MINOR semantics.** A minor QA finding keeps `qa_status == QA_SELECTED` and opens a `QA_FINDING` corrective action — that is what makes `ERR_OPEN_CORRECTIVE_ACTION` reachable independently of `ERR_RATER_QA_DEFICIT` (owed 0 / hold false in that instance).
5. **Coverage gaps closed at the end.** Added two state-machine instances for the transitions no recipe exercised: the QA `PASS` branch (narrower side-effect set than either failure branch) and `PROBATION → SUSPENDED → reinstate` (two FAIL_MINORs suffice; reinstate zeroes `qa_failure_count` while the two QA_FINDING actions stay OPEN).
6. **Assert-side endpoint fixes.** Three asserts referenced non-existent list routes (`GET /raters`, `GET /builders`, `GET /plan-models?subdivision_id=`); the RBAC instances now prove non-creation via the error envelope plus a positive retry, and the plan-code duplicate uses `GET /subdivisions/{id}/plan-models`.

## Step 3: Copy shared files — 2026-09-02T17:02:25.546Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-02T17:12:30.000Z

The PRD is complete and all three hard contracts pass.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_2413_hers_home_energy_rating_code_compliance_verification/workspace/PRD.md`

- **Final line count:** 469
- **Final section heading:** `## 5. Error Code Catalogue` (file ends with the last error row, `| ERR_PROGRAM_BUDGET_EXCEEDED | 422 |`) — no truncation, no audit footer.
- **Structure:** §1 Introduction (3 paragraphs) → §2 with 11 domain-derived subsections (2.1 Access Control, 2.2 Response Structure, 2.3 Pagination, 2.4 Common Resource Properties, 2.5 The Logical Clock, 2.6 Numeric Precision, 2.7 Code Edition/Climate Zone Reference Tables, 2.8 Validation Ordering, 2.9 Stale-Version Guards, 2.10 Conserved Ledgers & Cascade Integrity, 2.11 Certification Standing & Segregation of Duties) → §3 with 9 workflow subsections → §4 (44 rows, 4 columns) → §5 (44 rows, 2 columns).

### Hard Contracts Reports

```
Field coverage check:
- entities[].fields: 93 required, 93 present, 0 missing
- endpoints[].request_body: 53 required, 53 present, 0 missing
- endpoints[].query_params: 17 required, 17 present, 0 missing
- path_params + nested identifiers (home_id, code, amount_cents, current_utc): 4 required, 4 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 35 checked, 35 expressed in prose (§2.8 normative ordered pipeline), 0 missing
- concurrency_rules[] OCC rejections: 3 checked, 3 expressed (write_endpoint + expected_rating_version / expected_sample_set_version + error_id + 412 all named), 0 missing
- state_machines[].transitions: 37 checked (Rating 17, Inspection 2, SampleSet 6, QAReview 3, CorrectiveAction 5, Rater 4, DocumentPackage 3), 37 fully expressed, 0 missing
- calculations[]: 10 checked, 10 fully expressed in operator-free prose, 0 missing
- validations[] conditions: 35 checked, 35 matchable to error_id in §2/§3 prose, 0 missing
- endpoints[].side_effects / applies_to: 44 endpoints checked, all mutating side-effect sets expressed in §3, all applies_to scopes enumerated in §2.8, 0 missing
- entities[].fields[] structured content: 93 checked (types, defaults, initial values, derivation rules), 93 reconstructible from prose, 0 missing
- sibling-branch symmetry: 6 groups checked (QA PASS/FAIL_MINOR/FAIL_MAJOR; sample-set CLOSED_PASS/FAILED_EXPANDED; inspection PASSED/FAILED; registry ACCEPT/REJECT; corrective-action ACCEPT/REJECT/ESCALATE; confirm-from-PROJECTED vs confirm-from-ROUGH_IN_VERIFIED), 6 with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 806
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional verifications run: §2.2 is byte-identical to `section-2.2-response-structure.md`; all 44 endpoint rows match the scaffold's method+path exactly with zero role-list mismatches; all 44 error IDs appear in §2/§3 narrative *and* in the §5 table with the scaffold's HTTP statuses. As instructed, `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened.

**Orchestrator truncation guard (per skill instruction):** independently verified the PRD tail. File is 468 lines, 27 headings, ends with the complete final row of the §5 error-catalogue table at a real section boundary — not mid-sentence. All five top-level sections (§1–§5) present. No regeneration needed.

## Step 5: Generate unit tests — 2026-09-02T17:42:30.000Z

Generation is complete and verified.

## Files written

**`test_helpers/`** (Stage 1 infrastructure, 9 modules / 2,000 lines) — `api_client.py` (one method per §4 endpoint, raw `requests.Response`), `api_errors.py` (§5 catalogue + `set_error_http_status_map`), `constants.py` (`hers_index`, `normalize_blower_door`/`normalize_duct_leakage`, `round_half_up`, §2.7/§3.9 tables), `factories.py`, `fixtures.py` (action/read helpers + `RatingWorld`/`SampleWorld` composites + 8 pytest fixtures), `assertions.py`, `test_users.py`, `types.py`, `__init__.py`.

**`test_suite/`** — `conftest.py` plus 10 test modules:
- Queue B (corner, generated by two parallel workers): `test_01_entities.py` (11), `test_02_state_machines.py` (12), `test_03_calculations.py` (8), `test_04_validations.py` (14), `test_05_endpoints_and_errors.py` (5 fns / 13 cases), `test_06_rbac_and_layers.py` (6)
- Queue A (depth, written by me): `test_10_dual_variant_and_formula.py` (12), `test_11_state_machine_and_cascade.py` (8), `test_12_priority_precision_and_cross_entity.py` (12), `test_13_temporal_and_invariant.py` (8)

## Counts

- **104 tests collected** (96 test functions; one 9-way `parametrize` over the not-found routes). Collection only — the server was never running.
- **Difficulty (§1.8): 19 / 19 non-stub instances translated, 0 skipped**, 40 tests (every instance gets >=2 tests).
- **Corner (§1.9): 56 / 56 non-stub instances translated, 0 skipped**, 56 tests (one per instance). The 18 corner stubs carry `excluded_because` and are covered by queue A.
- **Zero instances failed the PRD-first two-condition filter**, so there are no gaps to report.

## Verification passes (all green)

- `pytest --collect-only` clean; `pyflakes` clean (only the intentional `noqa` re-exports in `conftest.py` / `test_helpers/__init__.py` flag).
- **PRD-citation pass**: every quoted sentence in all 96 docstrings is a literal (whitespace-normalized) substring of `workspace/PRD.md` — 0 failures.
- **Scaffold-citation pass**: exactly one trailing `Design:` line per test, correct position, 0 dual-tagged, 0 unresolved; 75 distinct instance names all exist in the source yaml.
- **Stub cross-reference pass** (the item the corner workers left open): all 18 `difficulty_instance:` references in `SCAFFOLD_CORNER_DESIGN.yaml` resolve to a real `rule_id / instance.name` pair in `SCAFFOLD_DIFFICULTY_DESIGN.yaml`.
- Every numeric literal re-derived independently from `test_helpers.constants` before being asserted (STD-2400 43->46, SOLAR-2400 26 vs 19, ODD-2135 46->47, BIG-3000 60->54/62, PERF 55, LOW 40, 1080->3.00 vs 1084->3.01, utility 80063+838+3330+29250 = 113481).

## Three judgement calls worth relaying

1. `SCAFFOLD_CORNER_DESIGN.yaml`'s `rating_rater_cannot_be_assigned_as_qa_reviewer` asserts `qa_status == QA_NOT_SELECTED`, which is not a PRD enum member; the test asserts §3.2's actual value `NOT_SELECTED`.
2. Two yaml sub-assertions were dropped as not uniquely derivable while the instances were still translated: the shape of the `POST /sample-sets/{id}/homes` 201 body (PRD never says which resource it returns — asserted through the following reads instead), and `line_items` on a *draft* utility package (§3.9 only writes them at issuance).
3. `remediation_accepted_then_reconfirm_restores_passing` advances the logical clock via the PRD's own clock endpoint before the second checkpoint, so §3.4's "newer than `confirmed_at`" holds under any reading of "newer".

`workspace/implementation/` was never read or written.

## Step 6: Generate implementation — 2026-09-02T17:32:00.000Z

The implementation is complete and verified.

## Files written
All under `workspace/implementation/`:

- `start.sh` (guarded pip install, then `exec python3 app.py`), `requirements.txt` (`Flask==3.0.3`)
- `app.py` — factory, 5 blueprints, `ApiError`/404/405/400-415/500 handlers, `PORT` env (default 10000), bind `0.0.0.0`, `strict_slashes=False`, `json.sort_keys=False`
- Infrastructure: `db.py` (in-memory dicts, logical clock, `new_row`/`touch`/`ordered`, request lock), `errors.py` (all 44 codes + 3 fallbacks), `response.py` (envelope, `Result`), `validation.py`, `auth.py`, `serializers.py`
- Domain: `calc.py` (all 10 calculations + §2.7 reference tables, exact `Decimal`), `graph.py`, `derived.py` (full-aggregation recompute + `reconcile()`), `cascades.py` (cascades A/B/C), `ops.py`
- Routes: `routes_core.py` (14), `routes_ratings.py` (9), `routes_field.py` (6), `routes_sampling.py` (7), `routes_qa.py` (8)

**Endpoint count: exactly 44** (verified by enumerating `app.url_map`). Storage is in-memory dicts only; nothing is seeded, and no file/SQLite/tmp state is touched.

## Verification performed
Booted via `bash start.sh` with `PORT=18413`, then drove a scripted end-to-end sweep touching every endpoint: builder -> subdivision -> plan model -> homes -> raters -> rating -> rough-in + final inspections with both diagnostic tests -> confirm (index 28, PASSING, ERI) -> QA review PASS -> UTILITY_PROGRAM draft + issue (ledger moved) -> registry submit + accept -> sampling (3 members, withdraw, select, tested confirm, close CLOSED_PASS with representative_index 28 propagated) -> failing confirmation -> corrective action submit/reject/resubmit/accept -> void (cascade C) -> post-void confirm rejected `ERR_RATING_VOID`. Zero failures. Also checked 401 (missing role, missing `X-User-ID`), 403, `ERR_INVALID_REQUEST` on `limit=0` and malformed JSON, list `meta` (`limit/offset/total_count/has_more`), unrouted 404, 405, `ERR_STALE_RATING_VERSION` ordering, and clock-driven `effective_certification_status: EXPIRED` with the rater row's `version` untouched. Server killed; `__pycache__` removed.

## PRD interpretation decisions
1. **Clock split** — `created_at`/`updated_at` use the wall clock; only `performed_at_utc`, `confirmed_at`, `issued_at` and cert-expiry comparisons read the logical clock (§2.5).
2. **`effective_certification_status` is read-time only** — advancing the clock disables a rater "without touching their row", so it is computed in the serializer and never bumps `version`.
3. **Void/lock precede state admissibility** — §2.8 orders step 7 (state) before steps 8-9, but explicitly says the void and lock checks are "deliberately not folded into" step 7, and §3.8 states a voided rating blocks confirmation, review assignment, remediation submission, package drafting and issuance "all with `ERR_RATING_VOID`". So `ERR_RATING_VOID`/`ERR_RATING_FILE_LOCKED` are decided before `ERR_INVALID_STATE` on those endpoints.
4. **`open_corrective_action_count` excludes `REJECTED`** (§3.1) while the unresolved-action gate for registry submission and issuance includes it (§3.7) — two distinct predicates.
5. **`qa_failure_count` is stateful** (incremented on FAIL_MINOR/FAIL_MAJOR, zeroed on reinstate), not a pure aggregate, because reinstatement resets it.
6. **Re-confirmation "newness" of the governing FINAL checkpoint is not enforced** — the PRD would have it compare an Inspection (no clock-derived timestamp) against `confirmed_at` (logical clock); any such comparison is ill-defined and would break the documented remediation cycle. Only "both governing tests present on a closed FINAL checkpoint" is required.
7. **`POST /sample-sets/{id}/close` accepts `SELECTED` as well as `TESTED`**, so closing a set whose tested rating is not yet confirmed yields `ERR_SAMPLE_SET_NO_TESTED_RATING` (explicit in §3.5/validation 28) rather than `ERR_INVALID_STATE`; `FORMING` and terminal statuses still give `ERR_INVALID_STATE`.
8. **`POST /plan-models` runs no certification checks** — the priority-12/13 `applies_to` lists omit it in both the PRD and the scaffold.
9. **`POST /inspections/{id}/tests` requires the checkpoint to be `SCHEDULED`** (`ERR_INVALID_STATE`), so the derived `failed_test_count` stays coherent with a closed checkpoint; the PRD states no explicit precondition.
10. **Client-supplied datetimes are echoed verbatim** (`cert_expires_at`, `scheduled_*_utc`); server-derived instants render with exactly 3 fractional digits and `Z`.
11. **Priority 18 on `select`** (`ERR_REPRESENTED_HOME_NOT_TESTABLE`) is unreachable for a `FORMING` set, so it is implemented only as the candidate filter.
12. **`touch()` bumps a row's version at most once per request**, so a cascade plus a direct mutation of the same row is a single increment; a global request lock plus a post-mutation `reconcile()` gives per-request atomicity of all derived fields.

## Step 7: Run tests and iterate — 2026-09-02T18:07:00.000Z

GREEN — all 8 parallel rounds report `104/104 passed, 0 failed, 0 errors, 0 skipped`.

## Summary

**Iterations run:** 2 sweeps (8 parallel rounds each, `setsid nohup`, distinct ports 33865/34343/35165/37761/41509/42153/46593/55881).
- Iteration 1 baseline: **93/104 in all 8 rounds**, the same 11 failures in every round — fully deterministic, zero flakiness signal.
- Iteration 2 after fixes: **104/104 in all 8 rounds**; union of non-passing tests across all 8 `results.$i.json` = **0**. All 8 files verified present on disk and parsed (`tests[].status` / `error_message`), left in place at `workspace/implementation/results.[1-8].json`.

**Tests deleted:** none. Every one of the 11 failures traced to a test-artifact defect, not to PRD silence or non-derivability — so nothing was deleted, nothing was weakened, no skip/xfail was added.

**Fixes applied to `test_helpers/`:**
- `test_helpers/fixtures.py` — `build_sample_world`: was rebinding `sample_set` to `add_sample_member`'s return value, which is the **Home** (PRD never states which resource `POST /sample-sets/{id}/homes` returns), so the second membership add used a home id as the sample-set id -> `404 ERR_SAMPLE_SET_NOT_FOUND`. Now captures `sample_set_id` before the loop, discards the per-add return value, and re-reads the set through `get_sample_set`. This single fixture bug caused **10 of the 11** failures — exactly the ">=5 tests share the same setup error -> suspect test_helpers" triage pattern.

**Fixes applied to `test_suite/`:**
- `test_suite/test_13_temporal_and_invariant.py` — `_added_then_withdrawn` returned the withdrawal response (a Home) and the caller asserted sample-set counters on it -> `KeyError: 'status'`. Now re-reads the set via `get_sample_set` before the §2.9/§2.10 assertions. (Its sibling `version == 3` assertion had been passing only coincidentally.)
- `test_suite/test_10_dual_variant_and_formula.py` — `_cedar_run_confirmed` held the **SELECTED** snapshot taken before `confirm_rating`, while the test asserts `status="TESTED"`. PRD §3.4 does advance the set SELECTED->TESTED as a side effect of confirming the TESTED home, so the rule is covered and uniquely determined; only the stale read was wrong. Now re-reads the set after `confirm_rating` (added `get_sample_set` to the import block).

**Fixes applied to `implementation/`:** **none.** All 17 implementation modules were read; no PRD violation was found. Storage remains in-memory dicts only — no seeding, no SQLite, no on-disk or `/tmp` state. No endpoint, field, side effect, or capability was added.

**Process note worth relaying:** grepping `FAILED [` out of `sweep.log` is unreliable here — 8 concurrent rounds interleave stdout on the same lines (visible in the log excerpt above, e.g. `PASSED [100%]` repeated 8x on one line). The per-round `results.$i.json` files are the only trustworthy source; the real schema is `{"total","passed","failed","errors","skipped","duration_seconds","tests":[{"name","file","status","duration_seconds","error_message"}]}`.

**Orchestrator verification (per standing guard against subagents claiming unverified clean sweeps):** independently confirmed all 8 `results.[1-8].json` exist on disk (33.8-33.9 KB each, mtime 18:06) and parsed each: every round reports 104 total / 104 passed / 0 failed / 0 errors / 0 skipped, ~182.4 s per round. The clean sweep is real.

## Step 8: Finalize PRD — 2026-09-02T18:10:00.000Z

Done — `PRD_FINALIZED.md` written with two surgical edits.

## Line counts
- `PRD.md`: 468 lines; `PRD_FINALIZED.md`: 468 lines — **0.0% line delta** (both edits are in-sentence appends to existing paragraphs; no new sections, no reflow).

## Changes
- **§3.5 (Membership)** — *insert* — pinned that `POST /sample-sets/{id}/homes` returns the updated **`Home`** in `data` (not the sample set), so the set's new `version`/counters require a re-read — `implementation/routes_sampling.py:167` (`return Result(home, home_out, status=201)`).
- **§3.5 (Withdrawal)** — *insert* — pinned that `POST /sample-sets/{id}/homes/{home_id}/withdraw` likewise returns the updated **`Home`** at `200`, so the set's post-withdrawal `status`/`version`/counters are observed only by re-reading the set — `implementation/routes_sampling.py:191` (`return Result(home, home_out)`).

## Step-7 items deliberately **not** patched
- `test_helpers/fixtures.py` (10 of 11 failures) and `test_suite/test_13_...` both traced to the *same* single PRD silence above — one root cause, two endpoints, two sentences.
- `test_suite/test_10_dual_variant_and_formula.py` (`_cedar_run_confirmed` stale snapshot): pure test-artifact staleness. §3.4 already states confirmation of a `TESTED` home advances the owning set `SELECTED`->`TESTED`, and `implementation/routes_ratings.py` does exactly that; `POST /sample-sets/{id}/select` returns the sample set, matching the test's own snapshot expectation. Nothing under-determined -> **no edit**.
- `implementation/` fixes: none in Step 7 -> no mismatch-driven edits.

## Per-edit pre-edit search log

**Edit 1 & 2 (shared subject).**
- **(a) Subject identified:** which resource object the two sample-set-membership mutations place in the success envelope's `data`.
- **(b) Impl paths enumerated / read:**
  - `routes_sampling.py:121-167` (add) and `:170-191` (withdraw) — both `Result(home, home_out)`, statuses 201 / 200.
  - Grepped **every** `return Result(...)` across `routes_core.py`, `routes_field.py`, `routes_qa.py`, `routes_ratings.py`, `routes_sampling.py` (all 40+ sites) to confirm these two are the *only* mutating endpoints that return a resource other than the one they create or address — `select`/`close` return the `SampleSet`, `confirm`/`void`/`submit-to-registry`/`registry-decision` return the `Rating`, `complete`/`submit`/`review`/`issue` return their own row. So the "not the sample set" clause stays local and contradicts nothing.
  - `serializers.py:22` `home_out` -> `_public(row)`, i.e. the full Home row minus `_`-prefixed keys; nothing sample-set-shaped leaks in, so "the updated `Home`" is accurate and complete.
  - `response.py:57-76` `Result.render` / `object_response` — confirms `data` holds exactly the serialized single row and the status passed by the view.
  - `auth.py:36-54` `endpoint` — `reconcile()` runs *before* `render()` on non-GET, so the returned row is post-derivation; `derived.py:46-73` shows `recompute_subdivision`/`recompute_sample_set` write counters onto the **subdivision/sample-set** rows, never onto the Home — hence no wording needed about derived fields on the response body.
  - `db.py:82-95` `touch` (once-per-row-per-request) — both the home and the set are bumped, which is why the "read the set back" phrasing refers to the set's `version` without asserting a specific number.
  - §4 routing table row for `POST /sample-sets/{id}/homes` and §4's 201 preamble — already fix `201 Created`; my wording reuses that status rather than restating or contradicting it.
- **(c) Wording adjustments made:** (i) said "The `data` of that `201` response" instead of introducing a status claim, to stay consistent with §4's existing 201 sentence; (ii) for withdrawal, phrased the consequence as the set's fields being "observed only by reading the set back" rather than naming a specific version/counter value, since `touch` semantics and §2.9's "+1 per successful withdrawal" already govern the numbers and a concrete figure would have been a new, narrower claim; (iii) avoided any statement that the set is *not* mutated — it is (`touch(sample_set)` plus `recompute_sample_set`) — the edits speak only about the response payload.

## Step 9: Complete PRD — 2026-09-02T18:25:00.000Z

`PRD_COMPLETED.md` is written and complete.

**File stats:** `PRD_FINALIZED.md` 468 lines / 90,613 chars -> `PRD_COMPLETED.md` 468 lines / 95,614 chars (**+5,001 chars**). All 22 changes are line-for-line in-paragraph replacements — no new paragraphs, no new sections, structure and final `§5` table row (`ERR_PROGRAM_BUDGET_EXCEEDED | 422`) intact.

**Counts:** 15 ambiguity-pins, 7 mismatch-revisions.

**Changes**

- §2.3 — insert — ambiguity — created_at ties keep creation order; a filter naming a nonexistent id returns an empty page, not 404 — `db.py:100`, `routes_core.py:125`
- §2.4 — insert — mismatch — `created_at`/`updated_at` are stamped from real elapsed time, not the logical clock — `db.py:74,95`
- §2.4 — insert — ambiguity — a row's `version` never advances more than once per request, however many writes/cascade hops land on it — `db.py:82`
- §2.5 — revise — mismatch — exactly four derivations read the logical clock; row bookkeeping and `api_request_timestamp` read real time; the clock may move backward; `data` carries `current_utc` alone — `db.py:58`, `routes_core.py:316`
- §2.8 step 7 — revise — mismatch — steps 8/9 precede general state admissibility on confirm, submit-to-registry, `POST /qa-reviews`, corrective-action submit and package issue; the numbered order holds only for the two inspection endpoints — `routes_ratings.py:155`, `routes_qa.py:63`, `routes_qa.py:280` vs `routes_field.py:132`
- §2.8 step 18 — revise — mismatch — `ERR_REPRESENTED_HOME_NOT_TESTABLE` applies to `/homes` alone; `/select` filters flagged homes and yields `ERR_NO_ELIGIBLE_SAMPLE_HOME` — `routes_sampling.py:197`
- §2.11 — insert — ambiguity — an acting `X-User-ID` resolving to no `Rater` row fails with `ERR_CERTIFICATION_INVALID`, not a 404 — `auth.py:67`
- §2.11 — revise — mismatch — `POST /plan-models` names no rater, so neither the standing nor the level gate applies to it — `routes_core.py:136`
- §3.3 — insert — ambiguity — measurements require a `SCHEDULED` checkpoint (`ERR_INVALID_STATE`); either test type is legal at either checkpoint; repeats allowed — `routes_field.py:132`
- §3.4 — revise — mismatch — governing final needs *at least* one of each test; newest qualifying checkpoint governs, and within it the latest reading of each type — `graph.py:204`
- §3.4 — revise — mismatch — re-confirmation does *not* require a checkpoint newer than `confirmed_at`, and it re-copies the measurements and re-snapshots `eri_target` — `routes_ratings.py:169`
- §3.5 — insert — ambiguity — selection ties beyond millisecond `created_at` fall back to registration sequence — `routes_sampling.py:242`
- §3.5 — insert — ambiguity — a routable tested rating that is neither `PASSING` nor `FAILING` is refused with `ERR_INVALID_STATE` — `routes_sampling.py:315`
- §3.5 — insert — ambiguity — a `REGISTERED` tested rating empties the step-one collection -> `ERR_SAMPLE_SET_NO_TESTED_RATING` — `routes_sampling.py:287`
- §3.5 — revise — ambiguity — represented homes' *live* rating (newest non-`VOID`) is rewritten; `compliance_path`, `stage`, `eri_target` untouched — `routes_sampling.py:305`
- §3.5 — revise — ambiguity — failing branch likewise acts on each sibling's live rating only — `cascades.py:132`
- §3.6 — insert — ambiguity — only `PROBATION` lifts the QA rate; `SUSPENDED`/expired raters stay at 0.10 — `calc.py:191`
- §3.6 hop four — revise — mismatch — the hop fires whenever the builder is not sampling-eligible after hops 1-3, including when nothing was revoked — `cascades.py:104`
- §3.6 — insert — ambiguity — a third or later failure leaves `certification_status` at `SUSPENDED` while `qa_failure_count` still rises — `cascades.py:41`
- §3.7 — insert — ambiguity — `remediation_note` is a mandatory non-empty string — `routes_qa.py:169`
- §3.8 — insert — ambiguity — the `outcome`-conditional payload fields are step-3 shape checks (422 before the 404) — `routes_ratings.py:269`
- §3.8 — insert — ambiguity — the void `reason` is a mandatory non-empty string — `routes_ratings.py:212`
- §3.9 — insert — ambiguity — a draft already carries `line_items` from the provisional variant (empty for `TAX_CREDIT_45L`) — `routes_qa.py:241`

Note: the subagent reported `test_helpers/` and `test_suite/` "do not exist in this workspace" — they live at the task root rather than under `workspace/`, so only `implementation/` was used as the alignment target. Since implementation is the sole normative alignment target for Step 9 and tests are explicitly non-authoritative, this does not affect the result.

**Orchestrator verification:** `PRD_COMPLETED.md` is 468 lines / 95,614 chars, ends on the real final boundary (last row of the §5 error-catalogue table, `ERR_PROGRAM_BUDGET_EXCEEDED | 422`) — not truncated. `diff` of the heading lists against `PRD.md` is empty: no sections added or removed. 24 lines revised in place across §2.3-§3.9.

## Pipeline complete — 2026-09-02T18:25:00.000Z

All nine steps finished. Final state: 3 scaffold artifacts, `PRD.md` (468 lines), `PRD_FINALIZED.md`, `PRD_COMPLETED.md`, 9-module `test_helpers/`, 10-module `test_suite/` (104 tests), 17-module Flask `implementation/` with 44 endpoints, and 8 passing sweep result files. Zero tests deleted, zero implementation fixes required in Step 7.
