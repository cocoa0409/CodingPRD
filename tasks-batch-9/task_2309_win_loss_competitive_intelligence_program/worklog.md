# Worklog — task_2309_win_loss_competitive_intelligence_program

## Step 1: Create task directory — 2026-09-01T15:03:15.000Z

Created `tasks/task_2309_win_loss_competitive_intelligence_program/` and `tasks/task_2309_win_loss_competitive_intelligence_program/workspace/` (pre-allocated task name used verbatim; no index scan performed).

## Step 2: Generate scaffold — 2026-09-01T17:51:17.000Z

All three deliverables are complete and lint-clean. Final state of `/home/ubuntu/github/CodingPRD/tasks/task_2309_win_loss_competitive_intelligence_program/`:

**SCAFFOLD.yaml** (§1.0–§1.7) — `difficulty_level: beyond_expert`, `entity_topology: graph`, `state_machine_shape: parallel` (with cyclic/branching/compound/posture-driven sub-shapes), `role_model: segregation_of_duties`, `consistency_model: immediate`, complexity layers: `optimistic_concurrency`, `cascading_side_effects`, `dual_variant_calculation`, `selector_policy`, `rate_threshold_triggers`.
- 14 entities, 9 state machines, 2 concurrency rules, 8 calculation rules, 38 validations (priority-ordered), 78 endpoints, 59 error codes, 6 roles (ProgramAdmin, ResearchAnalyst, LegalReviewer, EnablementManager, ProductManager, SalesRep).
- Core difficulty sources: dual selection bases (STRATIFIED_BY_SEGMENT vs VALUE_WEIGHTED) with a fully specified tie-break ladder that never uses `id`; a provisional/committed/final incentive ledger with tier multipliers and an external-vendor uplift applied to the already-rounded gross; a program incentive-posture ladder (OPEN → RESTRICTED at 0.85 → FROZEN at 1.0) with a status-driven floor; gap impact scoring with priority bands P0–P3 re-derived on every ratification; segregation of duties on attribution ratification and assignment completion.

**SCAFFOLD_DIFFICULTY_DESIGN.yaml** — single key `scaffold_difficulty_design`, 9 difficulty rules × 2 instances = **18 instances**.

**SCAFFOLD_CORNER_DESIGN.yaml** — single key `scaffold_corner_design`, **13 sections, 137 entries = 120 full instances + 17 `excluded_because` stubs** (each stub citing a real §1.8 instance name). Section breakdown: entities 14, state_machines 19, calculations 15, validations 37, endpoints 10, errors 17, rbac 11, optimistic_concurrency 3, cascading_side_effects 2, dual_variant_calculation 2, selector_policy 4, rate_threshold_triggers 2, consistency_model 1.

Verification results:
- `scaffold_lint.py`: **VERDICT: clean lint** — 78 endpoints declared, 14 entities, 18 §1.8 instances, 120 §1.9 instances, **1977 calls scanned**, all conforming to §1.5 and all §1.1 FKs reverse-reachable.
- All **59 error codes are triggerable** (a 59-line audit map is embedded as a header comment in the corner file); zero untriggerable codes.
- All **78 declared endpoints are actually invoked** as `- call:` at least once (the final append added the `POST /sampling-frames/{frame_id}/close` action plus two read-coverage instances that exercise every nested and flat collection endpoint with real filters and page windows).
- Every asserted numeric literal was hand-derived from the §1.3 formulas (selector scores 0.9956/0.8689/0.8378 and 1.3260/1.2521/0.8133/0.5668; incentives 250.00/150.00/312.50; posture ratios 0.8929 and 0.0250; gap impacts 36.40/P2, 57.20/P1, 62.40/P1, 5.20/P3; adoption 0.0000/0.3333/0.5000/1.0000).
- The hard constraint held: no sibling task directory under `tasks/` was listed, read, or grepped — the scaffold derives only from the 2309 scenario text and the generator skill's own spec plus its `references/claim-extraction-guide.md` and `examples/seed-tables-template.yaml`.

## Step 3: Copy shared files — 2026-09-01T17:51:17.000Z

Copied `./INSTRUCTION.md` → `tasks/task_2309_win_loss_competitive_intelligence_program/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-01T18:07:01.000Z

PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_2309_win_loss_competitive_intelligence_program/workspace/PRD.md`.

**Document:** 490 lines, `# Win-Loss Intelligence API — Product Requirements Document`, ends at §5 with no audit footer.

**Sections**
- §1 Introduction (3 paragraphs: independence, substantiation, fiscal containment).
- §2 Global Specifications — 11 subsections: 2.1 User and Role-Based Access Control, 2.2 API Response Structure (pasted verbatim from `section-2.2-response-structure.md`), 2.3 Pagination and List Ordering, 2.4 Common Resource Properties, 2.5 The Logical Clock, 2.6 Path Resolution / Tenancy / Reference Integrity, 2.7 Numeric Precision and Rounding Discipline, 2.8 Optimistic Concurrency on Parent Records, 2.9 The Incentive Ledger and Program Posture, 2.10 Validation Precedence, 2.11 Cascades and Derived-Field Reconciliation.
- §3 Business Logic & Workflows — 9 domain-grouped subsections (program lifecycle/guide; competitive registry, deals, buyers, analysts; sampling frames and the selector; interview scheduling; interview execution, incentives, no-show/reschedule/cancel; taxonomy, attribution, trend analysis; battlecard substantiation and legal review; publication, enablement, adoption; product-gap routing).
- §4 Endpoint Definitions — 4-column table, all 78 endpoints, 0 missing / 0 extra vs scaffold.
- §5 Error Code Catalogue — 2-column table, all 59 error IDs, every HTTP status matching the scaffold.

**Hard Contract 1 — Field-name coverage**
```
Field coverage check:
- entities[].fields: 149 required, 149 present, 0 missing
- endpoints[].input/request_body: 201 required, 201 present, 0 missing
- endpoints[].path_params: 55 required, 55 present, 0 missing
Status: PASS
```
(This scaffold carries list filters inside `input:` rather than a separate `query_params:` key, so they are counted in the 201.)

**Hard Contract 2 — Rule coverage (Zero-Silence)**
```
Rule coverage check:
- validations[] with priority: 38 checked, 38 expressed in prose as an explicit 1->38 ladder, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected_deal_version / expected_program_version + ERR_STALE_DEAL_VERSION / ERR_STALE_PROGRAM_VERSION all named), 0 missing
- state_machines[].transitions: 46 checked across 9 dimensions, 46 fully expressed with from/to, preconditions and side effects, 0 missing
- calculations[]: 8 checked, 8 fully expressed; 67 constants checked, 67 recoverable, 0 missing
- validations[] conditions: 38 checked, 38 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 96 side-effect entries checked, 96 expressed, 0 missing
- entities[].fields[] structured content: 149 checked, 149 reconstructible (enums, defaults, precision, derivations), 0 missing
- sibling-branch symmetry: 6 groups checked (APPROVE/CONDITIONAL/REJECT legal decision; LEGAL_REVIEW->APPROVED vs ->DRAFT join; ACCEPT/NEEDS_EVIDENCE/DECLINE triage; TRAINED vs FAILED quiz fork; SCHEDULED->CANCELLED vs NO_SHOW->CANCELLED; STRATIFIED_BY_SEGMENT vs VALUE_WEIGHTED, PROVISIONAL vs FINAL, RATIFIED_ONLY vs INCLUDE_PROVISIONAL variant pairs), 0 asymmetric
Status: PASS
```
32 of 46 transitions carry a literal `FROM → TO` arrow; the other 14 are self-loops, creations, multi-source auto-transitions or decision branches expressed as named prose (e.g. "moves the gap to `ACCEPTED`", "leave `status` where it is") — each verified individually.

**Hard Contract 3 — §3 path purity**
```
Path purity check (§3 only):
- backtick tokens scanned: 959
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

**Coverage notes**
- No pseudocode: no `>=`, `==`, `round(`, `min(`, `+=`, ` AND ` etc. outside the fenced §2.2 JSON blocks; no fuzzy quantifiers ("approximately", "roughly", "conservatively").
- Two constants are rendered as words rather than digits by design — the `CORROBORATED` level offset ("subtracting 1") and `CONDITIONAL_SURCHARGE` ("a surcharge of fifteen hundredths").
- Header naming: the scaffold's validation text says `X-Role`, but the skill fixes the contract names, so the PRD uses `X-User-ID` / `X-User-Role` throughout.
- Both `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened, grepped or referenced, and no sibling task directory was read.

## Step 5: Generate unit tests — 2026-09-01T20:07:00.000Z

Generation is complete and fully audited.

**Files created**

Stage 1 — `/home/ubuntu/github/CodingPRD/tasks/task_2309_win_loss_competitive_intelligence_program/test_helpers/` (9 files): `__init__.py`, `constants.py`, `api_errors.py` (59 `ERR_*` codes + status/precedence maps), `types.py`, `api_client.py` (82 endpoint methods), `test_users.py`, `factories.py`, `assertions.py`, `fixtures.py` (the `WinLossWorld` builder).

Stage 2 — `.../test_suite/` (23 files): `conftest.py` plus `test_01`–`test_22`.

**Test counts**

- **Queue A** (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`): 18 non-stub instances → **55 tests** across `test_01`–`test_09`, 18 distinct `Design: Difficulty/...` tags.
- **Queue B** (`SCAFFOLD_CORNER_DESIGN.yaml`): 120 non-stub instances → **120 tests** across `test_10`–`test_22`, one test per instance: entities 14, state_machines 15, calculations 9, validations 30, endpoints 10, errors 17, rbac 11, optimistic_concurrency 3, cascading_side_effects 2, dual_variant_calculation 2, selector_policy 4, rate_threshold_triggers 2, consistency_model 1.
- **Total: 175 tests, 138 design tags** (= 18 + 120).

**Instances skipped: none.** All 138 non-stub instances passed the PRD-first two-condition filter. The 17 `excluded_because:` stubs (state_machines 4, calculations 6, validations 7) correctly emit nothing. No `skip`/`xfail`/placeholder anywhere.

**Audit results**

- Tag audit: `tests 175 tags 138` — exactly one `Design:` line per test, no dual tags, no tags pointing at non-existent or stubbed instances; every quoted PRD string ≥8 words verified verbatim against `workspace/PRD.md`.
- Coverage audit over all 13 queue-B sections: every section `OK` with zero missing and zero extra instance names; totals `non-stub 120 / stubs 17 / emitted 120`.
- pyflakes: clean except the intentional fixture re-export warnings in `conftest.py` (pytest requires the names be imported to register the fixtures).

**PRD-first conflict resolutions worth flagging:** draw-batch responses assert **201** per PRD line 345 even where a design instance said "HTTP 200"; assertions that would have depended on undeclared list filters (`?deal_id=`, `?status=`, `?tier=`, `?program_id=` — the PRD declares only `limit`/`offset`, buyer-contact `email`, and the loss-trends window/basis/segment params) were re-expressed as unfiltered whole-collection `total_count` reads, path-scoped nested reads, or per-id GETs so every assertion stays uniquely derivable from the PRD.

## Step 6: Generate implementation — 2026-09-01T20:07:00.000Z

The implementation is complete and verified.

## Files created
All under `/home/ubuntu/github/CodingPRD/tasks/task_2309_win_loss_competitive_intelligence_program/workspace/implementation/`:

- **Launcher / deps**: `start.sh` (guarded pip install, then `exec python3 app.py`; binds `0.0.0.0`, `PORT` env, default 10000), `requirements.txt` (`Flask==3.1.3`)
- **App core**: `app.py` (registers 13 blueprints; error handlers for `ApiError`, 404, 405, generic `HTTPException`, and unexpected exceptions, all returning the error envelope)
- **Infrastructure**: `db.py` (in-memory `Store` over 14 dict tables, logical clock default `2026-08-01T00:00:00Z`, `new_row`/`touch`/`DerivedWatch`), `middleware.py` (`X-User-ID`/`X-User-Role` auth, 6 roles, `@endpoint(roles, analyst_identity=…)`), `validate.py` (enums + typed body/query extractors, FK resolution, pagination), `errors.py` (HTTP status map for all 59 error ids), `response.py` (object/array/list/error envelopes), `util.py` (Decimal ROUND_HALF_UP money/ratio helpers, ISO parsing/formatting)
- **Domain services**: `services/calc.py` (all derived fields: posture, incentive ladder with the two pinned rounding orders, selection rank, substantiation, 5-stage risk index, adoption, gap impact/band, frozen-metrics accessors), `services/serialize.py`, `services/cascade.py` (the three named cascades), `services/listing.py`
- **Routes** (13 modules): `clock, programs, competitors, deals, analysts, buyer_contacts, frames, interviews, loss_reasons, attributions, battlecards, enablement, product_gaps`

## Scale
**78 endpoints** registered (`url_map` has 78 non-static rules). Storage is in-memory dicts only; every table starts empty at boot — no seeding.

## Verification
- Booted exactly as the harness does: `PORT=10123 bash start.sh`, then live HTTP curls. `POST /_clock/set_current_utc` → 200, `POST /programs` → 201, `GET /deals` → 200 with `data: []` and pagination meta, `GET /nope` → 404 error envelope. `created_at` follows the logical clock while `api_request_timestamp` follows wall clock, as specified.
- Two end-to-end smoke scripts (kept outside the deliverable, in `/tmp`) pass: the happy path (frame draw → interview → responses → completion → ledger → attribution/ratify/supersede → loss trends → claim/legal/publish → enablement → gap promote) and a cycle/edge path (draw ordering and quota exhaustion, cooling-off across deals sharing a buyer email, no-show grace boundary, two reschedules then `ERR_RESCHEDULE_LIMIT_REACHED`, cancel-from-NO_SHOW, conditional surcharge → auto-approve, assignment fail/retry/past-due sweep, published-card claim rejection → withdrawal cascade with `published_at` retained per PRD, and program CLOSING/CLOSED cascades).

## One behavioral fix made in this pass
Product-gap metrics were being re-derived on every read, so ACCEPTED/DECLINED/PROMOTED gaps kept re-scoring — contradicting the PRD's "re-scores every product gap whose `status` is `NEW` or `TRIAGED`." Added `calc.gap_current_metrics` / `calc.freeze_gap_metrics`, freeze `_metrics` on ACCEPT and DECLINE, and routed serialization, list filtering/sorting, and the promote band gate through the frozen-aware accessor.

## Step 7: Run tests and iterate — 2026-09-02T07:25:13.000Z

All eight rounds are green. Final verification:

```
results.1.json 175/175 CLEAN    results.5.json 175/175 CLEAN
results.2.json 175/175 CLEAN    results.6.json 175/175 CLEAN
results.3.json 175/175 CLEAN    results.7.json 175/175 CLEAN
results.4.json 175/175 CLEAN    results.8.json 175/175 CLEAN
ALL EIGHT ROUNDS GREEN: True
```

## Summary

**Iterations run:** 9 full 8-round sweeps plus a per-slot retry pass (≈70 official rounds, ≈12,000 test executions), backed by 6 full-suite runs on a contention-free local per-test-restart harness.

**Tests deleted:** none. No test failed for PRD silence or non-unique derivability. Every genuine failure was a fixture that built a precondition the PRD forbids, or an assertion naming a field the PRD never defines — all repairable without weakening anything.

**Fixes applied to the test suite** (all in per-file fixtures/assertions; `test_helpers/` needed no changes):

| File | Fixture / assertion | Why |
|---|---|---|
| `test_suite/test_07_cross_entity_state_dependencies.py` | `_draft_card_under_a_closing_program` | Claim cited a response from a still-`SCHEDULED` interview; §3.7 requires evidence from a **completed** interview. Added the missing guide answers + `complete_interview`. |
| `test_suite/test_10_entities.py` | `_completed_chain_with_two_kinds_of_evidence` | Same violation; docstring said "completed" but the chain never completed. |
| `test_suite/test_11_state_machines.py` | `_card_in_legal_review_with_one_claim_decided`, `test_reopening_expires_the_untrained_rep_and_spares_the_trained_one` | Same; completed without moving the clock, since a sibling test asserts `decided_at == 2026-08-01T00:00:00.000Z`. |
| `test_suite/test_12_calculations.py` | `_published_card` | Same; clock held at the epoch for the `completed_at` assertion. |
| `test_suite/test_13_validations.py` | `_published_card_with_two_reps` | Same. |
| `test_suite/test_13_validations.py` | `test_evidence_from_outside_the_cards_program_is_refused` | Asserted `claim_count`, a field the PRD never names. Replaced with the PRD-named `approved_claim_count`. |
| `test_suite/test_14_endpoints.py` | `test_a_second_sweep_over_the_same_program_expires_nothing` | Same completion violation. |
| `test_suite/test_15_errors.py` | `test_an_approved_claim_refuses_a_second_decision` | Cited `EVALUATION_CRITERIA` (weight 0.70 → `UNSUBSTANTIATED`), so setup's `submit_legal` died on `ERR_CLAIM_UNSUBSTANTIATED`. Switched to `COMPETITOR_POSITIONING` (1.00 → `ANECDOTAL`). |
| `test_suite/test_15_errors.py` | `test_a_trained_assignment_refuses_a_replayed_pass` | Same completion violation. |
| `test_suite/test_16_rbac.py` | `test_the_author_of_an_attribution_cannot_ratify_it` | Asserted `ratified_at`, absent from the PRD. Replaced with `ratified_by_analyst_id`, which §3.6 does define. |
| `test_suite/test_16_rbac.py` | `test_the_pipeline_runs_only_when_every_role_holds_its_own_leg` | Conflated a triage *decision* with a *status*. PRD: `NEEDS_EVIDENCE` "moves the gap `NEW → TRIAGED`". Expected status corrected to `TRIAGED`. |

**Fixes applied to `implementation/`:**

| File | Function | Why |
|---|---|---|
| `routes/loss_reasons.py` | `amend_reason` | Error-precedence ordering. Re-parenting a depth-1 root under its own depth-2 child gives the node a legal new depth of 3, so the PRD's cycle rule owns the answer; descendant depth is undefined under a cycle. Cycle check now runs before descendant depths are projected → `ERR_TAXONOMY_CYCLE`, not `ERR_TAXONOMY_DEPTH_EXCEEDED`. |
| `routes/frames.py`, `routes/deals.py`, `routes/interviews.py`, `routes/buyer_contacts.py` | 7 `@endpoint` decorators gained `analyst_identity=True` | PRD line 21/141: the `ACTIVE`-analyst identity gate "guards every state-writing analyst operation". Missing on decline-selection, frame create/seal/close, response recording, contact create, and consent — so `ERR_SAMPLING_FRAME_NOT_FOUND` outranked `ERR_ANALYST_IDENTITY_INVALID`. |

Nothing was skipped, xfailed, downgraded to a status-only check, or seeded. A field/route audit confirms all 78 routes and every serialized field trace to PRD text, and `db.py` remains pure in-memory dicts, empty at boot.

**Environment note worth passing on:** the host was running 15+ sibling pipelines (load average 200–430, 240+ concurrent port holders). Under that load the runner's own port-reclaim step — `subprocess.run("lsof -ti:<port> …", timeout=5)`, hardcoded in `prd_bench_local_runner/pytest_plugin.py::_kill_port` — times out and reports as a *setup error*, not an assertion failure. Early sweeps showed 400–800 such errors per sweep with **zero** real failures; that 5s budget is unaffected by `--test-timeout`. Dropping peak concurrency to 2 rounds (per your batching guidance) and waiting for load to fall below ~100 eliminated it entirely. Raising that hardcoded timeout would make the runner far more robust on shared hosts.

**Orchestrator note:** two operational messages were sent to this subagent mid-loop — (1) launch sweeps detached via `setsid nohup` and poll for results files, because the 600s Bash-tool cap was killing in-flight rounds; (2) classify runner `lsof`/port-reclaim `TimeoutExpired` setup errors as host-contention noise (never grounds for deletion or implementation edits) and drop peak concurrency to 2 rounds. Neither message altered the PRD-first triage rules.

## Step 8: Finalize PRD — 2026-09-02T07:30:06.000Z

Done. `PRD_FINALIZED.md` written with three edits, all traceable to `<step_7_diff>` items.

## Line counts
- `PRD.md`: 490 lines → `PRD_FINALIZED.md`: 492 lines (+2 lines, +0.41%); three paragraphs touched.

## Changes
- **§2.1 (analyst identity gate)** — *revise* — replaced the eight-item enumeration of guarded operations with the full set of `ResearchAnalyst`-authorized operations (19), since the impl carries `analyst_identity=True` on every one of them — `implementation/middleware.py:30`, `routes/frames.py:24,67,83,117`, `routes/deals.py:159`, `routes/buyer_contacts.py:31,80`, `routes/interviews.py:116,220,268,295,338,366`, `routes/attributions.py:38,180`, `routes/battlecards.py:38,86,269,327`.
- **§2.10 rule 28 (taxonomy depth vs. cycle precedence)** — *insert* — pinned that only the addressed node's own projected `depth` is checked at rule 28, that descendant depths are projected after rule 29, and the two resulting outcomes — `implementation/routes/loss_reasons.py:126-140`.
- **§3.9 Triage** — *insert* — pinned that gap metrics are live while `NEW`/`TRIAGED` and frozen by `ACCEPT`/`DECLINE` (not by `NEEDS_EVIDENCE`), and that the frozen snapshot is what later reads, the list ordering/band filter, and promotion's band and adoption gates use — `implementation/services/calc.py:628-641`, `routes/product_gaps.py:145,150-155,169`, `services/serialize.py:239`, `services/cascade.py:41-48`.

## Per-edit pre-edit search log

**Edit 1 — subject: the `ERR_ANALYST_IDENTITY_INVALID` gate and its operation set.**
(b) Enumerated: `middleware.authenticate`/`endpoint` (only gate implementation; fires only when role is `ResearchAnalyst`); grepped every `@endpoint` decorator in all 14 route modules — confirmed all 19 `ResearchAnalyst`-authorized routes carry `analyst_identity=True` and zero `("ResearchAnalyst",)` decorators lack it; confirmed every `ANY_ROLE` read route and every other single-role route (`ProgramAdmin`, `LegalReviewer`, `EnablementManager`, `ProductManager`, `SalesRep`) does not; cross-checked §2.10 rule 4 and the §4 endpoint table for the same 19 rows.
(c) Wording widened from an item list to "every operation whose authorized role is `ResearchAnalyst`" plus the complete enumeration, so it cannot be read as excluding no-show/reschedule/cancel/reopen (which already had the flag and were also missing from the original list). Kept the identity predicate itself verbatim (exists + `ACTIVE`, no program-scoping), since the impl checks nothing more.

**Edit 2 — subject: taxonomy depth ceiling and acyclicity ordering.**
(b) Enumerated: `routes/loss_reasons.py::create_reason` (parent-derived depth only; new node has no descendants, no cycle path), `::amend_reason` (own-depth → cycle → subtree-height projection), `::_recompute_subtree_depths` (post-success), `calc.compute_depth`, `calc.subtree_height`, `calc.descendants_of_reason`, `calc.children_of_reason`/`is_leaf`; grepped `MAX_DEPTH`/`TAXONOMY_` repo-wide — no other depth or cycle check exists.
(c) Scoped the sentence to "on a re-parenting" for the descendant clause so it does not imply creation performs a descendant projection, and kept §3.6's existing depth prose verbatim (it still covers the descendant case loosely, matching the `new_depth + height - 1` test).

**Edit 3 — subject: product-gap derived metrics (freeze vs. live).**
(b) Enumerated: `calc.gap_metrics`, `calc.gap_current_metrics`, `calc.freeze_gap_metrics`, `calc.gap_linked_deals`, `calc.gap_derived_competitor_id`; `serialize.product_gap:239` (frozen-aware); `routes/product_gaps.py` intake (creates `NEW`, unfrozen), `list_gaps` band filter :109 and impact sort :111 (frozen-aware), triage ACCEPT gate :150 (live re-score, then stored as the freeze) / DECLINE :145 / `NEEDS_EVIDENCE` :139 (no freeze), `promote_gap` :169 (frozen band **and** frozen competitor feeding the adoption gate); `cascade.rescore_gaps_watch` (NEW/TRIAGED only) with its two callers `routes/deals.py:145` and `routes/attributions.py:116`.
(c) Two adjustments: (i) avoided a universal "every read uses the frozen snapshot" claim and instead named the specific read sites, because `list_gaps`' `derived_competitor_id` filter still traverses live; (ii) replaced "the cascades above" with "the deal-correction and attribution-supersede re-scorings" to match the existing §3.2/§3.6/§2.11 wording rather than implying a cascade defined in §3.9.

Also checked and deliberately **not** patched: the fixture-only Step 7 items (evidence cited from a non-`COMPLETED` interview — §3.7 already forbids it and the impl reports `ERR_EVIDENCE_SET_INVALID` under §2.10 rule 38; `claim_count`/`ratified_at` assertions naming non-PRD fields; the `NEEDS_EVIDENCE` → `TRIAGED` status; the `EVALUATION_CRITERIA` 0.70 → `UNSUBSTANTIATED` substantiation band). None of these revealed PRD silence or mismatch.

## Step 9: Complete PRD — 2026-09-02T07:49:07.000Z

Done. `PRD_COMPLETED.md` is written and aligned to `implementation/`.

## Deliverable
`/home/ubuntu/github/CodingPRD/tasks/task_2309_win_loss_competitive_intelligence_program/workspace/PRD_COMPLETED.md`

## Counts
- Source `PRD_FINALIZED.md`: 492 lines / 99,481 chars
- `PRD_COMPLETED.md`: 494 lines / 113,230 chars (+2 lines, +13,749 chars)
- 45 change sites: **38 ambiguity-pins**, **7 mismatch-revisions**
- One new paragraph only (the §2.3 list-filter inventory); no new sections; every other change is in-paragraph

## Changes
- §2.2 — insert — ambiguity — `api_request_id` is `req_` plus twenty uppercase alphanumerics — `implementation/response.py:11-12`
- §2.2 — insert — ambiguity — `api_request_timestamp` is the one real-wall-clock value — `implementation/response.py:15-20`
- §2.2 — insert — ambiguity — `has_more = offset + rows returned < total_count`; array responses carry none of the four list fields; money/ratios are JSON numbers — `implementation/response.py:39-53`
- §2.3 — insert — ambiguity — pagination accepts only plain base-ten integers, empty string means absent, loss-trend read is never paginated — `implementation/validate.py:193-228`
- §2.3 — insert — ambiguity — both buyer-contact collections use the default order; full ties fall back to server insertion order (`_seq`), never `id` — `implementation/services/listing.py:4-5`
- §2.3 — insert (new paragraph) — ambiguity — the complete per-list filter inventory, with enum/FK rejection codes and email normalisation — `implementation/routes/deals.py:84-109` and peers
- §2.4 — insert — ambiguity — `created_at`/`updated_at` are stamped from the logical clock, so rows written without a clock move share timestamps — `implementation/db.py:50-67`
- §2.5 — revise — mismatch — "nothing reads wall-clock time" corrected to except the envelope timestamp; clock setter returns 200 with the single echoed `current_utc` — `implementation/response.py:15`, `implementation/routes/clock.py:14-19`
- §2.5 — insert — ambiguity — output is exactly three fractional digits; input parser is lenient within ISO 8601 (optional seconds/fraction, space for `T`, offset or no zone) — `implementation/util.py:12-36`
- §2.6 — insert — ambiguity — body FKs are resolved only when present as JSON strings; otherwise they fall through to precedence 7; empty query filter is absent — `implementation/validate.py:283`
- §2.6 — insert — ambiguity — unknown query params ignored, absent body read as `{}`, undefined path/method answered `ERR_INVALID_REQUEST` at 404/405, trailing slash tolerated — `implementation/app.py:35,46-54`
- §3.1 — insert — ambiguity — supplied `required_question_keys` members are enum-validated but unbounded below; an empty array is stored — `implementation/routes/programs.py:39-41`
- §3.1 — insert — ambiguity — all three activation conditions report `ERR_PROGRAM_STATE_INVALID`, in order — `implementation/routes/programs.py:79-86`
- §3.1 — insert — ambiguity — both wind-down steps report `ERR_PROGRAM_STATE_INVALID` for state and precondition alike — `implementation/routes/programs.py:98-101,118-124`
- §3.1 — insert — ambiguity — budget-below-paid is `ERR_VALUE_OUT_OF_RANGE` evaluated after the version guard and state gate — `implementation/routes/programs.py:147-156`
- §3.1 — insert — ambiguity — all three guide-replacement breaches are `ERR_INVALID_REQUEST`, ahead of the state gate — `implementation/routes/programs.py:168-175`
- §3.2 — insert — ambiguity — archive has no state precondition and is repeatable, bumping `version` again — `implementation/routes/competitors.py:52-56`
- §3.2 — insert — ambiguity — deal correction accepts the empty subset; null `primary_competitor_id` clears rather than being ignored — `implementation/routes/deals.py:130-152`
- §3.2 — insert — ambiguity — contact email stored trimmed and lower-cased, uniqueness under that normalisation, no deal-state bar on adding contacts — `implementation/routes/buyer_contacts.py:40-44`
- §3.2 — insert — ambiguity — `NOT_REQUESTED` is not an accepted consent input; the consent write has no state precondition and is repeatable — `implementation/validate.py:34`, `implementation/routes/buyer_contacts.py:85-87`
- §3.2 — insert — ambiguity — a past `certified_until` is accepted at registration; deactivate has no state precondition — `implementation/routes/analysts.py:54-58`
- §3.3 — revise — ambiguity — seal gate order with per-gate codes (`ERR_FRAME_STATE_INVALID`, `ERR_PROGRAM_STATE_INVALID`, quota sum also frame-state) — `implementation/routes/frames.py:66-79`
- §3.3 — revise — ambiguity — `requested_count < 1` is `ERR_INVALID_REQUEST`; frame-not-sealed is `ERR_FRAME_STATE_INVALID`; a cross-program pinned deal is caught first — `implementation/routes/frames.py:118-135`
- §3.3 — insert — ambiguity — a pool short of the take count is not an error; fewer deals are drawn and 201 still returned — `implementation/routes/frames.py:142-169`
- §3.3 — insert — ambiguity — decline-selection refusal order and codes (two `ERR_DEAL_STATE_INVALID`, then `ERR_FRAME_STATE_INVALID`) — `implementation/routes/deals.py:165-174`
- §3.4 — revise — mismatch — staging order corrected (tenancy first as `ERR_CROSS_PROGRAM_REFERENCE`, then deal state, frame state, posture, then analyst `ACTIVE` as `ERR_ANALYST_IDENTITY_INVALID`); no interviewer-ownership check exists anywhere — `implementation/routes/interviews.py:135-156`
- §3.4 — insert — ambiguity — cooling-off reads `actual_end_at` for COMPLETED, `scheduled_start_at` for SCHEDULED, skips other statuses and the interview being rescheduled — `implementation/routes/interviews.py:41-56`
- §3.5 — insert — ambiguity — rating range is `ERR_VALUE_OUT_OF_RANGE` before the state test; `recorded_at` unconstrained; empty `competitor_name_verbatim` accepted; repeated question keys allowed — `implementation/routes/interviews.py:370-382`
- §3.5 — revise — mismatch — completion assigns `research_status` `INTERVIEWED` unconditionally, so a `SYNTHESIZED` deal is walked back rather than refused — `implementation/routes/interviews.py:261-262`
- §3.5 — insert — ambiguity — premature no-show is `ERR_INTERVIEW_STATE_INVALID`, checked after the source-state test — `implementation/routes/interviews.py:272-279`
- §3.6 — insert — ambiguity — null `parent_reason_id` promotes to root, an empty patch is a version-bumping no-op, neither amend nor deprecate has a state precondition — `implementation/routes/loss_reasons.py:119-163`
- §3.6 — revise — mismatch — weight range breach is `ERR_VALUE_OUT_OF_RANGE` (rule 8), not `ERR_WEIGHT_SPLIT_INVALID`; supersede skips the `INTERVIEWED` precondition — `implementation/routes/attributions.py:55-101`
- §3.6 — insert — ambiguity — `ERR_DUPLICATE_RESOURCE_KEY` fires only against a live `PROVISIONAL` row; a live `RATIFIED` row means supersede — `implementation/routes/attributions.py:68-71`
- §3.6 — revise — mismatch — trend rows tie-break on the *unrounded* accumulated weight; window params mandatory; response is a single unpaginated object with `segment_total` at 2dp — `implementation/routes/programs.py:238-318`
- §3.7 — insert — ambiguity — the card's author is the creating analyst's `X-User-ID`, held internally and not exposed — `implementation/routes/battlecards.py:54,227`
- §3.7 — revise — mismatch — a supplied empty `evidence_response_ids` is `ERR_INVALID_REQUEST` (not `ERR_EVIDENCE_SET_INVALID`); unresolvable ids are `ERR_INTERVIEW_RESPONSE_NOT_FOUND` first; claims writable only in DRAFT/LEGAL_REVIEW; the deduplicated array is what is stored — `implementation/routes/battlecards.py:91-131`
- §3.7 — revise — ambiguity — submit-legal gate order and codes, and `decided_at` reset to null on re-pending claims; response is the card — `implementation/routes/battlecards.py:273-298`
- §3.7 — revise — mismatch — segregation of duties is evaluated *after* every claim/card state test; wrong card state is `ERR_CLAIM_STATE_INVALID`; missing `conditions_note` is `ERR_INVALID_REQUEST`; response is the claim — `implementation/routes/battlecards.py:200-264`
- §3.7 — insert — ambiguity — `APPROVE` from `CONDITIONAL` retains the stored `conditions_note` — `implementation/routes/battlecards.py:231-235`
- §3.8 — revise — ambiguity — a non-`PUBLISHED` card on a training attempt yields `ERR_ASSIGNMENT_STATE_INVALID`, checked before the rep-identity test — `implementation/routes/enablement.py:86-101`
- §3.8 — insert — ambiguity — sweep scope covers all of the program's cards regardless of card status, ignores program status/posture, bumps each card once, writes nothing when empty; array ordering pinned — `implementation/routes/programs.py:324-350`
- §3.8 — insert — ambiguity — reopen requires `PUBLISHED` (`ERR_BATTLECARD_STATE_INVALID`) and retains `published_at` — `implementation/routes/battlecards.py:332-342`
- §3.9 — insert — ambiguity — `additional_response_ids` must resolve and be same-program (checked before the product-gap topic test); the stored array drops the source id and duplicates — `implementation/routes/product_gaps.py:38-67`
- §3.9 — insert — ambiguity — triage evidence additions persist even when the decision is refused; `ACCEPT` at P3 is `ERR_PRODUCT_GAP_STATE_INVALID` after the source-state test — `implementation/routes/product_gaps.py:122-153`
- §3.9 — revise — ambiguity — promote gate codes/order (`ERR_PRODUCT_GAP_STATE_INVALID` twice, then `ERR_PROGRAM_STATE_INVALID`); "most recently published" is greatest `published_at`, creation order as tie-break — `implementation/routes/product_gaps.py:167-187`

## Cross-checks run
All 59 error ids in `errors.py` appear in §5; all 78 implemented routes match the §4 table exactly (no extras either way); every field emitted by `serialize.py` is named somewhere in the PRD.
