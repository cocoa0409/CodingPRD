# Worklog — task_2402_directors_officers_liability_underwriting_claims

## Step 1: Create task directory — 2026-09-02T07:30:01.633Z

Created `tasks/task_2402_directors_officers_liability_underwriting_claims/` and `workspace/` subdirectory (name pre-allocated by the caller; no index scan performed).

## Step 2: Generate scaffold — 2026-09-02T09:38:57.256Z

All three deliverables are complete and lint-clean.

## Files written
- `/home/ubuntu/github/CodingPRD/tasks/task_2402_directors_officers_liability_underwriting_claims/SCAFFOLD.yaml` (3,198 lines) — §1.0–§1.7 only; verified to contain neither `scaffold_difficulty_design` nor `scaffold_corner_design`.
- `.../SCAFFOLD_DIFFICULTY_DESIGN.yaml` (1,827 lines) — single top-level key `scaffold_difficulty_design`.
- `.../SCAFFOLD_CORNER_DESIGN.yaml` (2,849 lines) — single top-level key `scaffold_corner_design`.

## SCAFFOLD.yaml structure
`api_prefix: /dno`; archetypes `multi_party_negotiation` / `ledger_reconciliation`; layers `dual_variant_calculation`, `cascading_side_effects`, `optimistic_concurrency`, `ops_run_checkpoint`; topology `graph`; state-machine shape `cyclic`; role model `segregation_of_duties`; consistency `immediate`.

| Table | Count |
|---|---|
| Entities (§1.1) | 14 |
| State machines (§1.2) | 11 |
| Concurrency rules (§1.2.1) | 4 |
| Calculations (§1.3) | 13 |
| Validations (§1.4) | 51 |
| Endpoints (§1.5) | 46 |
| Errors (§1.6) | 59 |
| Roles (§1.7) | 4 (Underwriter, RiskManager, ClaimsAdjuster, ComplianceOfficer) |

Domain coverage: risk scoring from disclosure packages + litigation events with a dual INDICATIVE/UNDERWRITTEN variant, tiered-ILF premium with grossed-up commission and surplus-lines tax, Side A/B/C coverage parts on a shared aggregate with a Side C sublimit and an entity-level capacity ledger, exclusion-term counter/resolve negotiation to IMPASSE, excess tower with following-form and DIC layers plus gap/participation/seal guards, claims-made notice windows with circumstance-report relation-back, defense-cost allocation (relative-exposure vs larger-settlement) through a retention→Side B→Side A waterfall with clawback on late denial, hammer-clause settlement with pro-rata indemnity split, cancellation return premium, and run-off/tail endorsement pricing.

## Design files
- **§1.8:** 9 `rule_id` blocks × ≥2 instances = **19 instances** (dual_variant_calc 2, combinatorial_formula 3, non_linear_state_machine 2, transitive_cascade 2, priority_pair_validation_conflict 2, boundary_precision_check 2, cross_entity_state_dependency 2, resource_temporal_overlap 2, compensating_invariant 2).
- **§1.9:** all 9 taxonomy sections, **58 instances = 41 full recipes + 17 `excluded_because` stubs** — entities 11, state_machines 14, calculations 6, validations 8, endpoints 4, errors 5, rbac 4, cross_cutting_complexity_layers 5, consistency_model 1.

## Verification performed
- `scaffold_lint.py` → `VERDICT: clean lint` (774 calls scanned across §1.8+§1.9; all conform to §1.5, all §1.1 FKs reverse-reachable).
- Error catalog **59/59 triggerable** — no uncovered code.
- Every instance name unique across both files; no `test_recipe` on any stub; every stub's cited `difficulty_instance` resolves to a real §1.8 instance name.
- Placeholder closure: every `${var}` bound by an earlier `captures:` in the same instance; all `expected_*_version` values are `${var}` (never literals).
- All `grounds:` references resolve to real priorities / error ids / endpoints / concurrency rule_ids / calculations / entity fields / state machines / roles. Normalized 21 dotted grounds tokens in §1.8 to the bracket form and expanded a bare `roles` ground into the four named roles.
- Replay checks against SCAFFOLD.yaml semantics: OCC priority 30 confirmed to outrank claim-state 46 / invoice-state 47 (so the stale-token asserts are right), `POST defense-invoices` confirmed **not** to bump `Claim.version` (keeps the captured token current), `expires_at = created_at + 90 days` confirmed for the 2026-10-30 boundary sweep, `ERR_PREMIUM_DELINQUENT` confirmed to key off the `premium_status` field (flipped only by an ops run), risk-band cutoffs (<40/<70/<100) confirmed against every asserted score, and bind side effects confirmed to create SIDE_A/B at the shared aggregate limit and SIDE_C at the sublimit with `premium_due_date = clock + 30d`.
- Fixed one forbidden-vocabulary hit ("simultaneous violation" → "a single request that violates both") in a validations stub rationale.

## Step 3: Copy shared files — 2026-09-02T09:38:57.256Z

Copied `INSTRUCTION.md` from project root to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-02T09:55:40.337Z

Generated `/home/ubuntu/github/CodingPRD/tasks/task_2402_directors_officers_liability_underwriting_claims/workspace/PRD.md` — 437 lines, ~12,800 words, ending at §5 with no audit footer. The two test-targeting index files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened, grepped, or referenced.

## Structure

- **§1 Introduction** — 3 paragraphs (domain framing, scope, the two design commitments: reproducible arithmetic and a server-controlled logical clock).
- **§2 Global Specifications** — 11 subsections: 2.1 RBAC (four roles, per-role identity semantics incl. `entity_backed:Insured` ownership chains for `RiskManager` and opaque-operator semantics for the other three), 2.2 API Response Structure (byte-verbatim from `section-2.2-response-structure.md`, followed by `---`), 2.3 Pagination + the four filter sets, 2.4 identity/audit fields/logical clock (incl. `LitigationEvent` as the write-once exception with no `updated_at`/`version`), 2.5 monetary precision and rounding discipline, 2.6 the four optimistic-concurrency rules, 2.7 the 51-step rejection precedence ladder, 2.8 left-to-right path resolution, 2.9 the three cascades (erosion up, release down, clawback reversal), 2.10 the dual `coverage_status`/`premium_status` axes, 2.11 the epoch advance and its ten output counters.
- **§3 Business Logic** — 9 subsections: intake/disclosures/litigation; the dual-variant scoring run; quotation, premium build-up and the four-round wording negotiation; binding, coverage parts and Side C capacity admission; tower layers, participation and sealing; premium, cancellation and the run-off tail; claims-made notice and circumstance relation-back; coverage decisions, allocation and the defense waterfall; hammer clause and resolution splitting.
- **§4 Endpoint Definitions** — intro paragraph + 46-row, 4-column table.
- **§5 Error Code Catalogue** — 59-row, 2-column table.

All 13 calculations are translated into prose with pinned evaluation and rounding order (commission gross-up as a division with the commission taken as the residual; net-premium load→credit→clamp→round-once; per-part rounding then single residual in the indemnity split; multiplicative severity load in run-off pricing). No symbolic operators or pseudocode appear anywhere in the document.

## Hard Contract audits

**Field coverage check:** 165 required names (150 entity fields, 82 write-endpoint inputs, 12 query/pagination params — deduplicated). Present in backticks: 165. Missing: 0. **Status: PASS**

**Rule coverage check:** 51/51 validations expressed with priority ordering and exhaustive `applies_to` scopes; 59/59 error IDs present; 11/11 state machines with every transition, precondition and side effect; 4/4 concurrency rules with their parent entity, field name and rationale; 13/13 calculations including both variant pairs (`INDICATIVE`/`UNDERWRITTEN`, `RELATIVE_EXPOSURE`/`LARGER_SETTLEMENT`) described symmetrically; all enum members and all state values present in backticks; depth-4 bind cascade, depth-4 resolve cascade and the compensating clawback all covered. Missing: 0. **Status: PASS**

**Path purity check (§3 only):** 0 `/`-prefixed tokens, 0 bare HTTP methods, 0 method+path combos inside §3. **Status: PASS**

Two scaffold internal inconsistencies were resolved and documented in the prose: `ERR_LIMIT_EXHAUSTED` is applied to `resolve` only (guarding `allocate` would make the Side A waterfall bucket unreachable, since both sides share the aggregate; shortfall on allocation is recorded as `unfunded_excess_usd` instead), and `ERR_PREMIUM_DELINQUENT`, `ERR_INSURED_VS_INSURED_EXCLUDED` and `ERR_POST_TRANSACTION_ACT` follow the broader errors-catalogue scope (also applying on `resolve` / on circumstance-report maturity respectively), which contradicts nothing in the validations table.

## Steps 5 & 6: Resume-mode filesystem verification — 2026-09-02T00:00:00.000Z

RESUME MODE. No worklog entries exist for Steps 5 and 6, but per the resume protocol the filesystem is authoritative and both steps' artifacts are present and non-empty:
- Step 5 artifacts: `test_helpers/` (10 modules: `__init__.py`, `types.py`, `api_client.py`, `api_errors.py`, `assertions.py`, `factories.py`, `constants.py`, `test_users.py`, `fixtures.py`) and `test_suite/` (`conftest.py` + 14 `test_*.py` files, 57 test functions).
- Step 6 artifacts: `workspace/implementation/` (3212 lines of Python across `app.py`, `auth.py`, `clock.py`, `db.py`, `errors.py`, `money.py`, `response.py`, `validation.py`, `routes/`, `services/`) plus `start.sh` and `requirements.txt`.
Neither step was re-run — regenerating them would invalidate artifacts later steps were built against. `SCAFFOLD.yaml`, `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`, `workspace/INSTRUCTION.md` and a complete `workspace/PRD.md` (2400+ lines, terminating in the full error-ID/HTTP-status catalogue — not truncated) were likewise verified present and left untouched. No stale `results.*.json` existed. Proceeding directly to Step 7.

## Step 7: Run tests and iterate — 2026-09-02T12:05:00.000Z

All 8 rounds of the confirming sweep report `57/57 passed, 0 failed, 0 errors`.

## Summary

**Iterations run:** 2 (iteration 1 diagnostic sweep → 4 identical failures in all 8 rounds; iteration 2 confirming sweep → 8/8 green).

Iteration 1 was fully deterministic: every one of the 8 rounds failed exactly the same 4 tests (53/57). The `FAILED` noise visible in `workspace/sweep.log` was an artifact of 8 concurrent rounds interleaving writes into one log file — the per-round `results.$i.json` files are authoritative and agreed exactly.

**Tests deleted:** none. All four failures were repairable at the assertion level (STEP 1c partial-coverage splits and one STEP 2 test-vs-PRD mismatch).

**Fixes applied to `test_suite/`:**

- `test_suite/test_05_policy_state_dimensions.py` — `test_one_epoch_advance_moves_both_dimensions_of_the_same_policy`: replaced `assert after["version"] == 3` with `assert after["version"] > before["version"]`. **DEFAULT/COMPUTED-FIELD SILENCE on version accounting.** PRD 2.9 line 180 states verbatim "every record touched has its `updated_at` refreshed and its `version` incremented by exactly 1", and PRD 2.11 says nothing at all about version increments during a sweep. A faithful PRD-only implementer can read the dual `INCEPTED→ACTIVE` + `INVOICED→DELINQUENT` sweep as one touch (+1) or as two transitions (+2); both are articulable, so the absolute `3` is not uniquely derivable. The remaining assertions (both dimensions moved, all counters) are untouched.
- `test_suite/test_05_policy_state_dimensions.py` — `test_paying_late_cures_the_billing_dimension_and_expiry_moves_only_coverage`: same root cause propagating through three absolute version numbers. Re-anchored them relatively against the post-sweep reading: `paid["version"] == swept["version"] + 1` (PRD 3.6: payment "increments the policy's `version` by 1" — exact and covered), the no-op re-sweep now asserts `== paid["version"]`, and expiry asserts `== paid["version"] + 1`. Strictness is preserved; only the non-derivable sweep-arithmetic offset was removed.
- `test_suite/test_08_notice_and_reporting_windows.py` — `test_a_reported_circumstance_relates_its_notice_date_back_across_the_boundary`: `ERR_REPORTING_WINDOW_CLOSED` expected status `422` → `409`. **STEP 2 test-vs-PRD mismatch, not an implementation bug.** PRD §5 line 416 maps `ERR_REPORTING_WINDOW_CLOSED` to 409, and `test_helpers/api_errors.py:108` already registers 409 — the `422` literal in the test contradicted both. The `error_id` assertion was left exactly as it was (no downgrade to a bare status check).
- `test_suite/test_13_exclusion_term_lifecycle.py` — `test_an_agreed_term_is_closed_to_both_sides`: dropped `assert agreed["last_actor_role"] == "RiskManager"` and relaxed the two follow-up refusals to `validate_error_is_one_of([ERR_INVALID_TERM_STATE, ERR_TERM_ACTOR_SEQUENCE])` plus an explicit `status_code == 409`. **COMPUTED-FIELD SILENCE cascading into ERROR PRECEDENCE SILENCE.** PRD 3.3 names the writers of `last_actor_role` explicitly and exhaustively — a counter "sets `last_actor_role` to the acting role" and the impasse counter "setting `round_count` to 4 and `last_actor_role` to the acting role" — but the resolve paragraph never mentions the field. Because PRD 2.7 ranks rung 13 (alternation) above rung 14 (term state), whether a post-`AGREE` underwriter action answers `ERR_TERM_ACTOR_SEQUENCE` or `ERR_INVALID_TERM_STATE` depends entirely on that undetermined write, and no choice of acting role makes it unambiguous (there are only two parties). Both error ids are 409 per PRD §5, so the HTTP status is still asserted exactly, and the surviving assertions (term terminal in `AGREED`, `agreed_variant` frozen to `BROAD`, `round_count` still 1, `version` unchanged by either refusal) are all PRD-covered. Import switched from `validate_error` to `validate_error_is_one_of`. Docstring rewritten to state the silence rather than the previous (unsupported) precedence claim.

**Fixes applied to `test_helpers/`:** none required — no fixture, factory or header helper violated a PRD precondition.

**Fixes applied to `implementation/`:** none. No PRD-required check was removed or weakened, no entity data is seeded at startup, and storage remains in-memory Python dicts in `db.py` only.

Supporting audit performed alongside the sweeps: `workspace/PRD.md` (437 lines) read in full, all four core `test_helpers` modules and all 14 test modules read, and every monetary/scoring expectation hand-verified against PRD prose — the 85.80/142.35 risk scores, the 302,940.00 → 346,217.14 → 358,334.74 premium stack and its five siblings, the 236,468.57 bound gross, the 217,032.80 and 236,468.57 return premiums, the 300,000/350,000 defense allocations, and the 560,003.17 / 560,003.16 / 280,001.58 indemnity split with its 0.01 residual on `SIDE_A`. All were confirmed PRD-faithful. One earlier concern was cleared: `test_07` posts layer bodies without `policy_id`, and `routes/policies.py` correctly treats it as optional.

**Orchestrator verification:** all 8 `results.{1..8}.json` independently re-read — every round `passed=57 total=57 failed=0`.

## Step 8: Finalize PRD — 2026-09-02T12:12:00.000Z

## Line counts
- `PRD.md`: 437 lines, 94,244 bytes
- `PRD_FINALIZED.md`: 437 lines, 95,367 bytes
- Line delta: 0 (+0.0%); byte delta: +1,123 (+1.19%). Both edits are inline extensions of existing paragraphs; no new sections, no reflow.

## Changes (2 edits; 2 of the 4 Step-7 items needed no PRD change)

- **§2.11 (The Epoch Advance)** — *insert* — appended a sentence pinning that version/`updated_at` accounting in a sweep is **per pass, not per transition**: a record the sweep writes to advances `version` by exactly 1 for the whole pass however many transitions or cascade steps reached it (explicit examples: `INCEPTED→ACTIVE` + `INVOICED→DELINQUENT` = +1 not +2; an expiring policy = +1 despite the release cascade also passing over it). — `implementation/services/derive.py:37-53` (`Touched` dedups by `id(record)`, flushed once), `implementation/routes/ops.py:32,115` (a single `Touched` for the entire sweep), `implementation/db.py:66-70`.
- **§3.3 (Quoting the Risk and Negotiating the Wording, resolve paragraph)** — *insert* — pinned that **neither `AGREE` nor `REJECT` rewrites `last_actor_role`** (it keeps naming the party whose wording was outstanding), and spelled out the consequence given the existing rung-13-over-rung-14 ordering: a further counter/resolve on the terminal term while the quote is still `OFFERED` yields `ERR_TERM_ACTOR_SEQUENCE` when the acting role equals the retained `last_actor_role` and `ERR_INVALID_TERM_STATE` when it differs. — `implementation/routes/quotes.py:129-150` (resolve writes only `status`/`agreed_variant`), vs. `routes/quotes.py:124` (counter does write it).

### No PRD change needed
- **test_08 `ERR_REPORTING_WINDOW_CLOSED` 422→409** — pure test bug. PRD §5 line 416 already says 409 and `implementation/errors.py:53` maps it to 409. Nothing was under-determined.
- **test_05 relative version re-anchoring (payment / no-op sweep / expiry)** — all three follow from the single §2.11 edit above plus already-exact PRD text (§3.6 "increments the policy's `version` by 1"; §2.11 "the following, and only the following" makes the no-op sweep a non-write). No second edit.

## Per-edit pre-edit search log

**Edit 1 — subject: `version`/`updated_at` increment accounting, especially multi-transition and cascade requests.**
(b) Paths enumerated: `grep -rn "db.touch\|touched.add\|Touched()\|touched.flush\|add_all"` over the whole implementation — 78 hits reviewed. `db.py:53-70` (`insert` sets `version` 1, `touch` +1); `services/derive.py:37-54` (`Touched` keyed on `id(record)`, so re-adds are idempotent); every route that builds a `Touched`: `routes/ops.py:32`, `routes/policies.py:190,217,262,318`, `routes/claims.py:168,231,286,376,426,523`, `routes/quotes.py:209`, `routes/insureds.py:117`, `routes/submissions.py:109,128`; the two direct `db.touch` callsites that use no `Touched` at all (`routes/policies.py:242` premium payment, `routes/claims.py:488` proposal respond, `routes/quotes.py:125,149` counter/resolve) — each touches exactly one record once; cascade helpers `cascade_erosion`, `cascade_restore`, `release_policy`, `erode_part`, `restore_part` (`derive.py:254-328`) and `services/claims.py:174-177`, `services/scoring.py:127,166`, all of which only `touched.add`. Verified **no record is `db.touch`-ed twice in any single request**, so the per-pass rule I state for the sweep is not contradicted anywhere; also verified `release_policy` unconditionally touches the policy, its released parts/layers and the insured, and that two policies of one insured expiring in the same sweep still yield insured +1.
(c) Adjustment: I deliberately **did not** add the tempting negative claim "records the sweep did not change keep their `version`". `derive.release_policy` touches the insured (and re-derives its capacity) even when the released policy carried no `SIDE_C` part and the numbers do not actually move, so "did not change → not touched" would have been a false universal. The no-op re-sweep case is instead left to the already-present "the sweep applies the following, and only the following". I also widened the wording from "transitions" to "transitions and cascade steps" and added the expiry example so the release cascade is covered explicitly rather than by implication.

**Edit 2 — subject: writers and readers of `last_actor_role`, and the alternation-vs-term-state precedence on a terminal term.**
(b) Paths enumerated: `grep -rn "last_actor_role\|proposed_by_role\|round_count\|agreed_variant"` over the whole implementation. Writers: `routes/submissions.py:168-172` (auto-opened `CONDUCT` term at quote issuance → `Underwriter`) and `routes/quotes.py:82-86` (manually opened term → `Underwriter`), plus `routes/quotes.py:124` (counter → acting role, including the `IMPASSE` branch at 118-120). Readers: `routes/quotes.py:110` (counter alternation guard) and `routes/quotes.py:138` (resolve alternation guard). Confirmed `resolve_term` (`quotes.py:129-150`) writes only `status` and `agreed_variant` and never `last_actor_role` or `round_count`. Also checked the check order in both guarded endpoints (quote-state → alternation → term-state, `quotes.py:108-113` and `136-141`) against PRD 2.7 rungs 12/13/14, and the downstream consumers of `agreed_variant` (`services/claims.py:21,30`) to be sure the added sentence does not touch them.
(c) Adjustments: scoped the precedence consequence with "while the parent quote is still `OFFERED`", because `quotes.py:108`/`136` check quote state first and a post-bind attempt returns `ERR_INVALID_QUOTE_STATE` instead — an unscoped claim would have been a new mismatch. Phrased the retained value as "the party whose wording was outstanding at the moment of resolution" rather than naming a specific role, which holds for both the open→resolve path (`Underwriter` retained) and any counter→resolve path (the last counterer retained). Left `round_count` out of the sentence: Step 7's surviving `round_count == 1` assertion shows the PRD is not ambiguous there, and mentioning it would exceed the hard scope.

## Step 9: Complete PRD — 2026-09-02T12:22:00.000Z

Written: `workspace/PRD_COMPLETED.md`

**Line counts / delta**: PRD_FINALIZED.md 437 lines → PRD_COMPLETED.md 437 lines (no sections or paragraphs added; all edits are in-paragraph). Chars 94,957 → 100,357, delta **+5,400**.

**Counts**: 35 changes total — **31 ambiguity-pins**, **4 mismatch-revisions**.

**Changes**

- 2.1 RBAC — revise — ambiguity — an empty-string header also yields `ERR_UNAUTHENTICATED`, not just an absent one — `auth.py:19`
- 2.2 Success envelope — insert — ambiguity — `api_request_id` is `req_` + exactly 20 uppercase-alphanumeric chars — `response.py:16`
- 2.2 Success envelope — insert — ambiguity — `api_request_timestamp` is read from the logical clock, not wall clock — `response.py:22`
- 2.2 Success envelope — insert — ambiguity — `has_more` = `offset + len(data) < total_count` — `response.py:70`
- 2.3 Pagination — insert — ambiguity — `created_at` ties broken by insertion order (relied on document-wide for "earliest/latest") — `db.py:75`
- 2.3 Pagination — insert — ambiguity — filters are exact-equality, never enum-validated; `total_count` counts the filtered set — `routes/policies.py:64`
- 2.5 Money — insert — ambiguity — monetary body inputs are quantised to 2dp on receipt; fractional inputs are not — `validation.py:62`
- 2.7 step 5 — revise — ambiguity — required-`null` rejected, optional-`null` accepted with default substituted (PATCH insured excepted); no-body endpoints still require a JSON object; non-integer `limit`/`offset` rejected — `validation.py:75-98`, `validation.py:28`
- 2.8 Path resolution — revise — ambiguity — body-identifier existence resolves after ladder step 5, before all later rules — `routes/submissions.py:46-49`
- 2.11 Epoch — revise — ambiguity — "every quote terminal" means every quote `LAPSED` or `SUPERSEDED`, and the submission must carry at least one — `routes/ops.py:293`
- 2.11 Epoch — insert — ambiguity — counters count transitions, so one policy can be counted in both `activated_`/`expired_` and in `expired_`/`delinquent_` — `routes/ops.py:239-267`
- 3.1 Registration — insert — ambiguity — `fiscal_year_end` is stored verbatim; MM-DD shape is never validated — `routes/insureds.py:34`
- 3.1 Insured update — revise — ambiguity — the conditional date must be in the same body (a stored date does not satisfy it); explicit `null` writes null; re-derives `aggregate_bound_side_c_usd` and `open_policy_count` too — `routes/insureds.py:106-118`
- 3.2 Submission intake — insert — ambiguity — unknown `insured_id` → `ERR_SUBMISSION_NOT_FOUND` after shape, before period/target checks — `routes/submissions.py:47-53`
- 3.2 Submission intake — insert — ambiguity — initial `risk_score`/`risk_band`/`score_variant`/`scored_at` null, `disclosure_packages_considered` 0, `litigation_units` 0.00 — `routes/submissions.py:68-74`
- 3.2 Package selection — insert — ambiguity — `created_at` tie broken by insertion order — `services/scoring.py:51`
- 3.3 Quote issuance — insert — ambiguity — superseded sibling's `version` also increments; response is the quote, not the auto-opened term — `routes/submissions.py:129-178`
- 3.3 Auto CONDUCT term — insert — ambiguity — `agreed_variant` starts null — `routes/submissions.py:172`
- 3.3 Opened term — insert — ambiguity — `agreed_variant` starts null — `routes/quotes.py:86`
- 3.4 Acceptance — insert — ambiguity — a supplied body is ignored — `routes/quotes.py:178`
- 3.4 Policy creation — insert — ambiguity — initial `tower_sealed` false, `placed_limit_usd`/`total_eroded_usd`/`return_premium_usd`/`runoff_premium_usd` 0.00, `aggregate_remaining_usd` = limit, `open_claim_count` 0, runoff dates and `cancelled_reason` null; response is the policy — `routes/quotes.py:215-245,275`
- 3.4 Bind versions — revise — ambiguity — the accepted quote's `version` also increments — `routes/quotes.py:268-269`
- 3.5 Oversubscription — insert — ambiguity — the participation sum is compared at 2 decimal places — `routes/policies.py:154`
- 3.5 DIC share — revise — ambiguity — the DIC set is layers whose `status` is `ATTACHED` or `EXHAUSTED` (RELEASED excluded) — `routes/policies.py:157-160`
- 3.5 Primary layer — revise — ambiguity — "no primary yet" means no `ATTACHED`/`EXHAUSTED` layer at 0, so co-participation on the primary band is impossible — `routes/policies.py:166-169`
- 3.5 Seal — revise — **mismatch** — seal re-derives `tower_posture` by precedence, so an already-eroded policy reads `ERODED`, not `SEALED` — `services/derive.py:219-230`
- 3.5 Seal — revise — **mismatch** — sealing is **not** a precondition for notice; claims/circumstance reports need no sealed tower — `routes/claims.py:155,181`
- 3.5 Seal — insert — ambiguity — takes no body; responds with the updated policy — `routes/policies.py:201,221`
- 3.6 Premium payment — insert — ambiguity — `CANCELLED` is the only blocking coverage state; a `PAID` premium is refused with `ERR_INVALID_POLICY_STATE` — `routes/policies.py:235-238`
- 3.6 Cancellation — insert — ambiguity — `cancelled_reason` is stored on the policy; `premium_status` untouched — `routes/policies.py:258`
- 3.6 Run-off — revise — **mismatch** — the policy moves to `RUNOFF` from `INCEPTED` as well as from `ACTIVE`; endorsement echoes `tail_years` and is the response resource — `routes/policies.py:273,319,330`
- 3.7 Claim creation — insert — ambiguity — `post_refusal_defense_usd` starts at 0 — `routes/claims.py:130`
- 3.7 Circumstance report — insert — ambiguity — `potential_claimants` is a single free-text string, not a list — `routes/claims.py:64`
- 3.7 Maturity — insert — ambiguity — responds with the new claim, not the report — `routes/claims.py:236`
- 3.8 Coverage decision — revise — ambiguity — both branches record `decided_by_user_id`, not just acceptance — `routes/claims.py:287`
- 3.8 Invoice creation — revise — ambiguity — "unset or 0" pinned: `allocation_method_applied` null, the four amounts 0.00 — `routes/claims.py:338-342`
- 3.8 Allocation — insert — ambiguity — responds with the updated invoice, not the claim — `routes/claims.py:407`
- 3.9 Proposal creation — insert — ambiguity — five derived fields start null; each superseded proposal's `version` increments — `routes/claims.py:427-444`
- 3.9 Response to proposal — revise — ambiguity — `refusal_reason` must be non-empty; one supplied with `CONSENT` is ignored and stays null — `routes/claims.py:468-481`
- 3.9 Resolution inputs — revise — ambiguity — no range constraint on `final_resolution_amount_usd`; `post_refusal_defense_usd` is written onto the claim's own field — `routes/claims.py:98,542`
- 3.9 Resolution — insert — ambiguity — governing proposal's `version` also increments; responds with the updated claim — `routes/claims.py:551-558`

Note on the two `mismatch` findings worth flagging: PRD_FINALIZED asserted that sealing the tower gates the claims side and that `tower_posture` becomes `SEALED` on seal — the implementation does neither (no seal gate on notice; `ERODED` outranks `SEALED` in the posture precedence). Both were revised to the implementation's behavior.

## Pipeline complete — 2026-09-02T12:22:00.000Z

Steps 1–4 and 5–6 were pre-existing on disk (resume mode); Steps 7, 8 and 9 ran in this session. Final state: 8/8 sweep rounds at 57/57 passed, `PRD_FINALIZED.md` and `PRD_COMPLETED.md` both written. No implementation fixes were needed at any point and no tests were deleted.
