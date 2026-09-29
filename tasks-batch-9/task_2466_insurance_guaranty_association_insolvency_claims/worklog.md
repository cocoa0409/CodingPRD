# Worklog — task_2466_insurance_guaranty_association_insolvency_claims

## Step 1: Create task directory — 2026-09-02T20:57:21.735Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2466_insurance_guaranty_association_insolvency_claims` and its `workspace/` subdirectory. Index 2466 was pre-assigned by the invoking pipeline (no ./tasks/ scan performed, per instruction — concurrent pipelines on this host).

## Step 2: Generate scaffold package — 2026-09-02T22:25:00Z

Wrote `SCAFFOLD.yaml` (§1.0–§1.7), `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8) and
`SCAFFOLD_CORNER_DESIGN.yaml` (§1.9) from the scenario text plus the scaffold-generator
spec only — no sibling task under ./tasks/ was inspected.

Shape: 12 entities, 47 endpoints, 8 roles, 7 calculations, 49 errors, 46 validation rules,
3 OCC concurrency rules, difficulty band `beyond_expert`.
§1.8: 21 instances across all 9 difficulty rules (2/3/2/2/3/2/2/2/3).
§1.9: 70 real instances + 14 `excluded_because:` stubs across all 9 taxonomy sections.

`scaffold_lint.py` → `VERDICT: clean lint` (732 calls scanned; 47 endpoints, 12 entities).

## Step 2 (orchestrator record): Generate scaffold — 2026-09-02T22:27:30.000Z

Verbatim subagent summary:

Scaffold package for task_2466 is complete and lint-clean.

Files written (all in `/home/ubuntu/github/CodingPRD/tasks/task_2466_insurance_guaranty_association_insolvency_claims/`):
- `SCAFFOLD.yaml` — §1.0–§1.7 only; contains neither `scaffold_difficulty_design` nor `scaffold_corner_design`
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` — single top-level key `scaffold_corner_design`

(`worklog.md` and `workspace/` were pre-created by the pipeline in Step 1; I appended a Step 2 entry to the worklog.)

Shape — difficulty band `beyond_expert`, above the Expert band on every axis:
- 12 entities: Insolvency, CoverageProfile, MemberInsurer, Assessment, MemberAssessment, ProofOfClaimTransfer, TransferredPolicy, CoveredClaim, OtherInsuranceCoverage, VendorAssignment, UnearnedPremiumRefund, SisterAssociationReferral
- 47 endpoints, 8 roles (AssociationAdmin, ReceiverLiaison, CoverageAnalyst, ClaimsAdjuster, DefenseCounsel, ClaimsCommitteeOfficer, AssessmentOfficer, MemberInsurerAgent) under a segregation-of-duties model
- 49 error codes, 46 prioritized validation rules (auth → existence → shape → OCC → state → business), 3 OCC `concurrency_rules`
- 7 calculations, 2 of them dual-variant: `claim_net_payable` (OFFSET_THEN_CAP vs CAP_THEN_OFFSET, threshold), `unearned_premium_refund` (pro-rata vs short-rate, chronological), `distribution_waterfall` (class 1/2/3, waterfall_allocation), `member_assessment_allocation` (bps caps + capped-excess redistribution, constraint_propagation), `recoupment_surcharge_projection`, `insolvency_ledger_recompute`, `vendor_fee_accrual`
- 5 state machines (Insolvency, CoveredClaim, ProofOfClaimTransfer, Assessment, MemberAssessment — the last with parallel billing/recoupment dimensions), branching shape, `immediate` consistency, 7 complexity layers

Design-file counts:
- §1.8: 21 instances covering all nine difficulty rules (dual_variant_calc 2, combinatorial_formula 3, non_linear_state_machine 2, transitive_cascade 2, priority_pair_validation_conflict 3, boundary_precision_check 2, cross_entity_state_dependency 2, resource_temporal_overlap 2, compensating_invariant 3)
- §1.9: 84 entries = 70 full `test_recipe` instances + 14 `excluded_because:` stubs, across all nine taxonomy sections (entities 12, state_machines 13, calculations 11, validations 24, endpoints 6, errors 3, rbac 5, cross_cutting_complexity_layers 9, consistency_model 1)

Verification: `scaffold_lint.py` reports `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5` over 732 scanned calls. Additional checks I ran: all 49 catalog error codes appear in the design files (none untriggered), every `excluded_because:` citation resolves to an existing §1.8 instance name, no stub carries a `test_recipe`, all 84+21 instance names are unique across both files, and every real instance has the four required recipe sections. Hard constraint respected — no sibling `tasks/task_*/` content was listed, read, or grepped; everything derives from the scenario text, `SKILL.md`, and `references/claim-extraction-guide.md`.

Orchestrator verification: SCAFFOLD.yaml 2617 lines, SCAFFOLD_DIFFICULTY_DESIGN.yaml 1395 lines, SCAFFOLD_CORNER_DESIGN.yaml 3496 lines; both design files have the correct single top-level key; SCAFFOLD.yaml contains 0 occurrences of either design key.

## Step 3: Copy shared files — 2026-09-02T22:28:31.407Z

Copied `./INSTRUCTION.md` → `tasks/task_2466_insurance_guaranty_association_insolvency_claims/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-02T22:39:00.000Z

Verbatim subagent summary:

PRD generated at `workspace/PRD.md` — **443 lines**, ending cleanly at the final row of the §5 error table.

**Hard constraint respected:** neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped, or referenced. Only `SCAFFOLD.yaml`, `SKILL.md` and `section-2.2-response-structure.md` were read.

Sections: §1 Introduction (3 paragraphs); §2 with 10 subsections (2.1 RBAC, 2.2 API Response Structure verbatim, 2.3 Pagination, 2.4 Resource Identity/Versioning/logical clock, 2.5 Money/Cents/Rounding, 2.6 OCC on ledger-bearing writes, 2.7 Closed Estate Ledger + derived counters, 2.8 Path Resolution/Request Shape/Validation Precedence with the full 47-step priority cascade and `applies_to` scopes, 2.9 Statutory Coverage Configuration, 2.10 Insolvency-Wide Write Gates + `immediate` consistency model); §3 with 10 subsections organised as an estate lifecycle timeline (triggering event → receiver record transfer/conversion → unearned premium refunds → claim presentation & screening → other insurance/non-duplication → contracted vendors & administrative expense → recommend/remand/approve → multistate referrals → assessments, caps & recoupment → estate cash, waterfall & wind-up); §4 47-row routing table (Method, Path, Description, Authorized Role(s)); §5 49-row error catalogue.

Coverage confirmation: Entities 12/12. Endpoints 47/47 (all present in §4, path-matched). Error codes 49/49 in §5 and all 49 named in §2/§3 narrative. Validation rules 49/49 (incl. priorities 11.5/17.5/25.5), priority-ordered in §2.8 with full `applies_to` enumerations. Calculations 7/7 (`claim_net_payable` both `cap_order_mode` variants, `unearned_premium_refund` both variants, `distribution_waterfall` both allocation modes, `member_assessment_allocation` 3-round capped redistribution, `recoupment_surcharge_projection`, `insolvency_ledger_recompute`, `vendor_fee_accrual`). State machines: all 9 declared in the scaffold (Insolvency, TransferredPolicy, ProofOfClaimTransfer, CoveredClaim, OtherInsuranceCoverage, VendorAssignment, UnearnedPremiumRefund, Assessment, MemberAssessment with parallel billing/recoupment dimensions), ~40 transitions with preconditions + error ids + side effects. Concurrency rules 3/3. Roles 8/8.

Note: the task brief said "5 state machines / 46 validation rules"; the scaffold actually declares 9 `state_machines` entries and 49 `validations` entries. I covered the scaffold's actual contents, not the brief's counts.

Hard Contract reports — Field coverage: entities[].fields 121/121, endpoints[].request_body 75/75, endpoints[].query_params 12/12 → PASS (two mechanical passes; all 62 state/enum values verified as standalone backticked tokens, with a fix applied for `CONVERTED`/`PARTIALLY_CONVERTED`/`REJECTED`, plus every `records`-element key and the `distributions`, `settlement-worksheet` and clock response shapes). Rule coverage: validations 49/49, OCC rejections 3/3, transitions 40/40, calculations 7/7, validation conditions 49/49, side_effects/applies_to 47/47, entity field structured content 121/121, sibling-branch symmetry 11 groups all with equal prose density → PASS. Path purity (§3 only): 822 backtick tokens scanned, 0 leading-`/` tokens, 0 bare HTTP-method tokens, 0 combined method+path tokens → PASS. Also verified: §2.2 byte-identical to the reference, zero pseudocode operators, zero fuzzy quantifiers.

Orchestrator truncation check (per known doc-generator failure mode): `wc -l` = 442, `wc -c` = 97645. Tail inspected — the file ends with the complete final row of the §5 error table (`| ERR_INSUFFICIENT_ESTATE_FUNDS | 422 |`), a real section boundary, not mid-sentence. §5 contains 49 `ERR_` rows and §4 contains 47 endpoint rows, matching the scaffold. No regeneration needed.

## Step 6: Generate implementation — 2026-09-02T23:32:00.000Z

Orchestrator note: this subagent was terminated mid-run by a transient upstream API error ("The system encountered an unexpected error during processing") after writing auth.py, calc.py, envelope.py, errors.py, requirements.txt, shape.py, start.sh, store.py and an empty routes/. Judgement call (no user available to consult, per AUTONOMY): rather than discard and re-spawn from scratch, the orchestrator resumed the SAME subagent with its context intact and an explicit inventory of what was already on disk plus a restatement of every hard constraint. Resuming preserves the design decisions already baked into the half-written modules; a fresh subagent would have had to reverse-engineer them from the partial files or overwrite them inconsistently. The resumed run completed normally and its verbatim summary follows.

Verbatim subagent summary:

Implementation is complete and boot-verified.

Files written (all under `workspace/implementation/`): `start.sh` (10 lines; launcher: `cd $(dirname $0)`, ensure flask, `exec python3 app.py`); `requirements.txt` (1; `flask==3.0.3`); `app.py` (68; app factory, blueprint registration, `ApiError`/404/405/HTTPException/500 envelope handlers, `app.run(host=0.0.0.0, port=$PORT or 10000)`); `store.py` (161; 12 in-memory dicts, logical clock starting at exactly `2026-08-01T00:00:00Z`, id/timestamp/version/sequence helpers); `errors.py` (75; all 49 error ids → HTTP statuses, `ApiError`, `fail()`); `envelope.py` (58; `meta`/`response_type`/`data` envelope, pagination meta, error envelope); `auth.py` (73; 8 roles, vendor-role→vendor_type map, `endpoint()` decorator with 401 before 403); `shape.py` (228; priority-14 body validation — types/enums/ranges/unknown-field — plus pagination and query filters); `calc.py` (248; all 7 calculations in exact integer/`Fraction` arithmetic, 4 round-half-up sites, 2 truncate-then-residual sites); `domain.py` (606; collection lookups with 7 distinct 404s, derived-on-read counters, claim payable recompute, cascades, 12 serializers); `routes/__init__.py` (13); `routes/core.py` (714; 14 endpoints — coverage profiles, insolvencies, trigger, estate remittances, distributions, close, POC transfers + convert, clock); `routes/policy_routes.py` (230; 5 endpoints — policies + unearned-premium refunds); `routes/claim_routes.py` (732; 17 endpoints — claims, screen, worksheet, other insurance, vendor engagements + invoices, recommend/remand/approve, referrals + respond); `routes/funding.py` (414; 11 endpoints — member insurers, assessments + certify, member assessments, payments, surcharge filings, recoupment remittances). Total 3631 lines.

Coverage: 47/47 endpoints, verified by enumerating `app.url_map` (exactly 47 non-static rules, matching the SCAFFOLD paths one-for-one). 8 roles, all 49 error ids in the catalog, 7 calculations, every declared state-machine transition (including parallel `billing_status`/`recoupment_status` dimensions, remand-with-revert ≤ 2, referral `pre_referral_status` restore, supersede-on-re-engagement), the 3 OCC rules (`expected_claim_version` / `expected_policy_version` / `expected_insolvency_version` → the three 412s), and the PRD §2.8 precedence cascade including the fractional priorities (11.5, 17.5, 25.5), vendor-ownership-before-404 on `recommend`/`invoices`, vacuous SoD/member-ownership so the 404 wins, and body-FK 404 before shape 400. Storage is in-memory dicts only; nothing is seeded — a fresh process starts with 12 empty collections and the clock at `2026-08-01T00:00:00Z`.

Boot check: `PORT=18471 bash start.sh` in the background, then `GET /coverage-profiles` → `HTTP/1.1 200`, body `{"data":[],"meta":{...,"limit":10,"offset":0,"total_count":0,"has_more":false},"response_type":"array"}` — well-formed, empty store, `api_request_timestamp` `2026-08-01T00:00:00.000Z`; `POST /coverage-profiles` → 201 with the full profile object (id + created_at only, no `updated_at`/`version`, defaults applied). Server killed afterwards; port confirmed closed. Additionally two throwaway probe scripts (since deleted) were run against a booted server: a 34-step happy-path walk (profile → insolvency → policy → trigger cascade → claim → screen → other-insurance chain → engagement → invoice → worksheet → recommend → remand → recommend → approve → refund → estate remittance → distribution run → member insurer → assessment → certify → surcharge → remittance → payment → settle bubble-up → clock advance → POC batch → convert → close) all returning the expected statuses, and a 21-step error probe confirming each of the 401/403/404/400/405/412 cascade orderings resolves to the intended error id with no tracebacks in the server log.

## Step 5: Generate unit tests — 2026-09-03T00:30:00.000Z

Orchestrator note: like Step 6, this subagent was terminated mid-run by a transient upstream API error, after writing all nine `test_helpers/` files and six of the eventual seventeen `test_suite/` files (34 `Design:` tags on disk at the time). Same judgement call, same reasoning as Step 6: the orchestrator resumed the SAME subagent with its context intact, handing it an on-disk inventory (file names + line counts + current tag count), an explicit instruction to re-read its own files before continuing and not to re-emit an instance an existing test already covers, and a restatement of the design-index-only contract, the PRD-first skip filter, and the ban on reading `workspace/implementation/` (which by then existed and would have contaminated the tests). The resumed run completed normally.

Orchestrator note on step ordering: Steps 5 and 6 were launched as two background Agent calls issued back-to-back rather than as two tool uses inside one assistant message, so `test_suite/` did not exist for the first ~10 minutes of Step 6's run but did exist later. The skill's physical-isolation guarantee was therefore not available for the whole of Step 6, and was replaced by an explicit prohibition in both prompts: Step 6 was told not to read `test_suite/` or `test_helpers/` even if they appeared while it worked, and Step 5 was told not to read `workspace/implementation/`. Both subagents reported honouring this.

Verbatim subagent summary:

Test generation for `task_2466_insurance_guaranty_association_insolvency_claims` is complete and all audits pass.

Files written: Stage 1 — `test_helpers/` (2261 lines): `__init__.py`, `api_client.py`, `api_errors.py` (calls `set_error_http_status_map`), `assertions.py`, `constants.py`, `factories.py`, `fixtures.py`, `test_users.py`, `types.py`. Stage 2 — `test_suite/` (5696 lines): `conftest.py` plus 17 numbered files, `test_01_statutory_payable_variants.py` through `test_17_concurrency_windows_and_derived_reconciliation.py` (5–13 tests each, grouped into domain-named classes, ordered simple → complex).

Test count and design coverage: **122 tests**, all collected cleanly (`pytest --collect-only` → 122). **Queue A (§1.8 difficulty): 21/21 instances translated, 0 skipped**; every instance carries ≥2 tests. **Queue B (§1.9 corner): 70/70 non-stub instances translated, 0 skipped for the PRD-first filter.** The 14 `excluded_because:` stubs were correctly *not* translated (4 calculations, 4 state_machines, 4 validations, 2 cross_cutting) — each is deliberately deferred by the corner design to a named §1.8 difficulty instance, so no gap results. Tag hygiene: 0 untagged, 0 dual-tagged, 0 dangling tags; every `Design:` line is the last line of its docstring.

Verification run at the end: Strict verbatim-citation checker (PRD normalized to single-spaced text; every docstring paragraph must be a contiguous PRD substring): **0 misses across all 122 tests**. This closed the last 10 defects — six were non-adjacent PRD sentences joined inside one paragraph (split into separate paragraphs in `test_10` ×2 → resolved by extending each quote to the true end of its PRD sentence, `test_11`, `test_12`, `test_15`, `test_16`), and four were genuinely non-verbatim text re-quoted from the PRD: the approval three-guard sentence (PRD 280) in `test_14`, the other-insurance registration payload sentence (PRD 256) in `test_15`, the full cascade item 26 including its `ERR_INSOLVENCY_ALREADY_TRIGGERED` clause (PRD 155) and the real "Approval is the moment the estate takes on a hard liability…" sentence (PRD 280) in `test_16`. `pyflakes` clean on `test_suite/` and all helpers except the intentional re-export barrel `test_helpers/__init__.py` (already annotated `# noqa: F401`); removed two genuinely unused imports from `test_helpers/fixtures.py`. `py_compile` clean; zero occurrences of `skip`/`skipif`/`xfail` or the word "scaffold" anywhere in `test_suite/`.

One design-vs-PRD divergence was resolved in the PRD's favour and is worth flagging: corner instance `errors/writes_against_a_closed_insolvency_return_insolvency_closed` proposes triggering via `POST /claims`, but PRD cascade item 25 routes `POST /claims` on a closed file to `ERR_INSOLVENCY_NOT_TRIGGERED`, and item 26 lists `POST /policies` among the endpoints that return `ERR_INSOLVENCY_CLOSED`. The test therefore triggers with `POST /policies`.

## Step 7: Run tests and iterate — 2026-09-03T00:33:53.496Z

Verbatim subagent summary:

Clean sweep. All 8 parallel rounds green at 122/122.

**Iterations run:** 2 (sweep → single-cause fix → sweep).

**Iteration 1 result:** 113/122 in all 8 rounds — 9 deterministic failures (identical union in every round, no flakiness).

**Root cause (one, shared by all 9):** every failure was a byte-string comparison of a *logical-clock instant*, e.g. `assert '2026-08-01T00:00:00.000Z' == '2026-08-01T00:00:00Z'`. The implementation renders domain timestamps with three fractional digits; 11 assertion sites across 8 test files demanded zero fractional digits.

**STEP 1 finding — partial coverage (STEP 1c split):** PRD §2.4 verbatim covers the *instant*: "The clock's startup default is exactly `2026-08-01T00:00:00Z`", "Every `created_at`, and every domain timestamp — `filed_at_utc` on a covered claim, `triggered_at_utc` on an insolvency file, `certified_at_utc` on an assessment, `recommended_at_utc` on a claim recommendation and `responded_at_utc` on a referral — is stamped from that clock", and §3.1 "`proof_of_claim_deadline_utc` as the `liquidation_order_date` advanced by 365 calendar days, at the instant `00:00:00Z` on that date". PRD is **silent on the rendering width of the domain `*_at_utc` fields** — the three-fractional-digit rule in §2.4 is stated only for `created_at`/`updated_at`. Two-reader test: Reader A renders all clock-stamped fields uniformly with three fractional digits (consistent with §2.4 and §2.2's `api_request_timestamp`); Reader B echoes the bare-second form. Both are PRD-faithful, so the *format* half of the assertion is not uniquely derivable, while the *instant* half is. Per STEP 1c the covered assertion was kept and the uncovered one removed — no test deleted, and no assertion weakened below what PRD states (the instant is still pinned exactly, to the millisecond).

**Fixes applied to `test_helpers/`:**
- `test_helpers/assertions.py` — added `_parse_instant()` + `assert_instant_equals(actual, expected, message)`: parses ISO 8601 UTC tolerating any fractional-digit width and compares the resulting instants. Exported automatically via the existing `from .assertions import *` barrel in `test_helpers/__init__.py`.

**Fixes applied to `test_suite/`** (11 sites; each swapped exact-string equality for `assert_instant_equals`, preserving the original failure message, plus the import line):
- `test_03_member_assessment_allocation.py:137` (`certified_at_utc`)
- `test_04_claim_recommendation_and_engagement_cycles.py:242` (`responded_at_utc`)
- `test_05_validation_precedence_pairs.py:136` (`proof_of_claim_deadline_utc`)
- `test_07_cross_entity_state_gates.py:111` (`triggered_at_utc`)
- `test_09_entity_shapes_and_derived_fields.py:107, 300` (`proof_of_claim_deadline_utc`, `filed_at_utc`)
- `test_10_lifecycle_transitions.py:258` (`triggered_at_utc`)
- `test_13_intake_refund_and_referral_validations.py:200, 220, 226` (deadline ×2, `filed_at_utc` on the boundary instant)
- `test_17_concurrency_windows_and_derived_reconciliation.py:324` (`certified_at_utc`)

**Fixes applied to `implementation/`:** none. No PRD-required check was removed or weakened, no endpoint/field/side-effect was added, and storage remains in-memory only.

**Tests deleted:** none. Test count is unchanged at 122 (`pytest --collect-only` → 122); `pyflakes` clean on `test_suite/` and the edited helper.

**Iteration 2 result:** 122/122 in all 8 concurrent rounds (`results.1.json` … `results.8.json`, all complete JSON, verified individually).

Orchestrator independent verification (the claimed-clean-sweep-with-no-artifacts failure mode is a known hazard, so the orchestrator re-checked rather than taking the summary at face value):
- All 8 `workspace/implementation/results.{1..8}.json` exist, each ~42 KB, all written 00:27, all parse as complete JSON, and each reports `passed=122 total=122 failed=0`.
- `find test_suite test_helpers workspace/implementation -name '*.py' -newer results.1.json` returns empty — every source file predates the green results, so the green sweep genuinely exercised the current code rather than a pre-fix snapshot.
- Hygiene: 0 occurrences of `xfail` / `mark.skip` / `skipif` anywhere in `test_suite/` or `test_helpers/`; 122 `Design:` tags for 122 tests (1:1).
- Persistence: 0 hits for `sqlite3` / file-write `open(...,'w')` / `json.dump` / `pickle` / `/tmp` across the implementation — storage is in-memory only, as required for per-test-server isolation.
- The new `assert_instant_equals` was read directly: it compares parsed instants with `==`, so it still pins the exact millisecond and is a genuine STEP 1c coverage correction, not an assertion weakening.

Orchestrator note on an apparent timing anomaly, recorded for honesty: an orchestrator-side poll ~10 minutes into Step 7 tailed `workspace/sweep.log` and saw a `[ 2%]` progress marker, which suggested rounds lasting hours and was inconsistent with the subagent's total reported runtime of ~17 minutes for two full sweeps. The artifact evidence above resolves it — `sweep.log` is shared by all 8 concurrent rounds and is overwritten at each sweep launch, so a tail of it mid-relaunch is not a reliable progress signal. The results files themselves are consistent and complete, so the green verdict stands on artifact evidence rather than on the log tail.

Step 8 is NOT skipped: Step 7 ran 2 iterations with 1 `test_helpers/` fix and 11 `test_suite/` fixes, so the skip condition (zero iterations beyond baseline) does not hold. The PRD silence Step 7 identified — rendering width of the domain `*_at_utc` fields — is a real PRD-vs-implementation under-determination that Step 8 should pin.

## Step 8: Finalize PRD — 2026-09-03T00:44:00.000Z

Verbatim subagent summary:

Done. `PRD_FINALIZED.md` created with two edits, both tracing to the single root cause in `<step_7_diff>` (byte-string comparison of logical-clock instants: impl renders three fractional digits, PRD pinned that width only for `created_at`/`updated_at`).

Line counts: `PRD.md` 442 lines / 97,645 bytes; `PRD_FINALIZED.md` 442 lines / 98,527 bytes; delta **0 lines (0.00%)**, +882 bytes (+0.90%) — both edits are in-paragraph prose insertions/revisions, no new sections or lines.

Changes:
- **§2.4 (Resource Identity, Versioning and the Logical Clock)** — *insert* — after the sentence listing the clock-stamped domain timestamps, added one rendering convention: every instant-valued field the API emits (`created_at`, `updated_at`, `api_request_timestamp`, the domain `*_at_utc` fields, `proof_of_claim_deadline_utc`, `current_utc`) is ISO 8601 UTC with exactly three fractional digits whenever non-null, so the startup instant renders `2026-08-01T00:00:00.000Z`; plus a scoping clause excluding date-valued fields. — `implementation/store.py:55-68` (`fmt_dt`), `store.py:71` (`now_iso`), `envelope.py:20`, `routes/core.py:711`
- **§3.1 (Opening the Insolvency File…)** — *revise* — `proof_of_claim_deadline_utc` described as "at the instant `00:00:00Z` on that date" → "at the instant midnight on that date, stored and rendered as `00:00:00.000Z`". — `implementation/routes/core.py:215`

Per-edit pre-edit search log:

**Edit 1 — §2.4 rendering convention.** (a) Subject: the rendered width of every instant-valued field emitted anywhere by the API (and, by contrast, of date-valued fields). (b) Impl paths enumerated (grepped `_at_utc|current_utc|deadline|fmt_dt|now_iso`, then `"[a-z_]*_utc"` exhaustively, then all `F(..., "date")` / `"datetime"` shape declarations): `store.py:55-68 fmt_dt` — sole formatter, hardcodes `%03d` milliseconds; `store.py:71 now_iso`; `store.py:141-149 stamp_new` (`created_at`/`updated_at`); `store.py:152-156 touch` (`updated_at`); `envelope.py:20` — `api_request_timestamp` on both success and error envelopes; `routes/core.py:213` `triggered_at_utc`, `:215` `proof_of_claim_deadline_utc` = `"%sT00:00:00.000Z"`, `:153/:155` null initial values, `:658` `filed_at_utc` on conversion-materialised claims, `:673` `recommended_at_utc` null, `:711` `current_utc` via `fmt_dt`; `routes/claim_routes.py:135` `filed_at_utc`, `:546` `recommended_at_utc` set, `:568` cleared to null on remand, `:668` `responded_at_utc` null on referral create, `:719` set on respond; `routes/funding.py:167` `certified_at_utc` null on draft, `:245` set on certify; `domain.py:364/366/414/498/514/589` — the six serializers that echo these fields verbatim (no reformatting at serialize time); exhaustive `_utc` field census: exactly seven fields (`certified_at_utc`, `current_utc`, `filed_at_utc`, `proof_of_claim_deadline_utc`, `recommended_at_utc`, `responded_at_utc`, `triggered_at_utc`) — all three-digit, none date-only; date-valued side: `shape.py:130-136` strict `YYYY-MM-DD` validator, used at `core.py:137` (`liquidation_order_date`), `claim_routes.py:92` (`loss_date`), `:401-402` (`engagement_start/end`), `policy_routes.py:43-44` (`effective_date`/`expiration_date`), and `store.py:130-133 date_to_str` writes `coverage_termination_date` and `cancellation_date`; off-Step-7 path that forced a rewording: `routes/core.py:624-682 _materialise_policy/_materialise_claim` — the poc-transfer conversion pass copies `effective_date`, `expiration_date` and `loss_date` through `_as_text()` with **no** date-format validation (conversion only screens `MISSING_REQUIRED_FIELD` / `UNKNOWN_LINE_OF_BUSINESS` / `NO_MATCHING_POLICY`), so a receiver record can persist a non-`YYYY-MM-DD` string. (c) Wording adjustment: the draft second half read "…are unaffected and stay in bare `YYYY-MM-DD` form." That universal claim is falsifiable on the conversion path just above, so it was re-scoped to a purely negative statement — "are outside it and are never rewritten into instant form" — which asserts only that the three-digit convention does not reach them, making no claim about their content. Also added "whenever it is non-null" to the positive half, since `triggered_at_utc`, `proof_of_claim_deadline_utc`, `certified_at_utc`, `recommended_at_utc` and `responded_at_utc` are all legitimately null at various lifecycle points (and `recommended_at_utc` is re-nulled by remand at `claim_routes.py:568`). Named `created_at`/`updated_at` without claiming both always exist, preserving the coverage-profile exemption already stated one paragraph above.

**Edit 2 — §3.1 deadline literal.** (a) Subject: the concrete stored/rendered value of `proof_of_claim_deadline_utc`. (b) Impl paths enumerated: `routes/core.py:215` (the only write, literal `"%sT00:00:00.000Z"`); `routes/core.py:153` (initialised null pre-trigger); `domain.py:364` (serialize, verbatim echo); the two consumers of the field, `routes/claim_routes.py:115-117` and `routes/policy_routes.py:175-177`, both of which re-parse via `store.py:93-127 parse_datetime` — whose `_DT_RE` accepts 1-6 fractional digits and an omitted fractional part, so the boundary comparison `store.now > deadline` is width-insensitive and unaffected by pinning the literal. Also confirmed §2.8 rule 28 and §3.4 describe the boundary as an instant comparison with no format literal, so no companion edit is needed there. (c) Wording adjustment: kept "at the instant midnight on that date" as the semantic statement and appended the rendering ("stored and rendered as `00:00:00.000Z`") rather than replacing the instant description, so the boundary-inclusive rule in the same sentence ("filings at exactly that instant are still accepted") continues to read as an instant comparison and does not imply a string comparison.

No other `<step_7_diff>` items required PRD changes — Step 7 applied no `implementation/` fixes, deleted no tests, and weakened no assertion below what PRD states (the instant remains pinned to the millisecond in the test suite).

## Step 9: Complete PRD — 2026-09-03T01:03:00.000Z

Verbatim subagent summary:

`PRD_COMPLETED.md` is complete and verified. Structural check passed: heading list byte-identical to `PRD_FINALIZED.md` (no sections added or renamed), §2.8 cascade still exactly 47 numbered items, all 100 table rows intact.

Deliverable: `workspace/PRD_COMPLETED.md`. `PRD_FINALIZED.md` (source) 442 lines / 98,527 chars; `PRD_COMPLETED.md` 444 lines / 112,361 chars; delta +2 lines / **+13,834 chars**. 42 lines changed across 38 hunks (32 `Edit` calls). Every edit is an in-paragraph insert or revision; the only hunk that added lines is the §2.8 request-shape paragraph, which split into two. **31 ambiguity-pins, 8 mismatch-revisions.**

Changes:
- §2.1 — revise — ambiguity — auth header absent **or empty string** both give `ERR_UNAUTHENTICATED` — auth.py:45-51
- §2.3 — insert — ambiguity — non-integer `limit`/`offset` and invalid enum filter values are `ERR_INVALID_REQUEST`; identifier filters matched literally; undeclared query params ignored — shape.py:190-224
- §2.3 — insert — ambiguity — ties on equal `created_at` broken by server-side insertion order on every list — store.py:159-161
- §2.4 — revise — ambiguity — `to_iso8601` required, any parseable instant accepted including backwards moves; response is exactly `current_utc` + `delinquent_member_assessment_count` — core.py:688-714
- §2.8 — revise — **mismatch** — `ERR_REFERENCED_ROW_NOT_FOUND` covers only `POST /policies|/claims|/assessments` and only for string values; poc-transfers reports `ERR_INSOLVENCY_NOT_FOUND` from the path — policy_routes.py:28-33, core.py:426
- §2.8 — insert — ambiguity — empty/whitespace strings rejected; JSON null == absent; absent body == `{}`; non-object body rejected; enumerates the 10 domain checks that report `ERR_INVALID_REQUEST` and the two that run late — shape.py:69-96, core.py:81-92/140-145/203-207/431-445
- §2.8 item 3 — insert — ambiguity — vendor ownership precedes existence (403 over 404); invoices re-checks acting engagement and `ASSIGNED` after shape with the same code — claim_routes.py:32-51, 501-505
- §2.8 items 4-5 — insert — **mismatch** — member-ownership and segregation checks pass vacuously when the row is missing (404 stands); segregation also vacuous when `screened_by_user_id` is null — funding.py:33-38, claim_routes.py:580-589
- §2.8 item 19 — insert — ambiguity — only 3 other-insurance layer transitions legal, others `ERR_CLAIM_INVALID_STATE`, checked after the claim-status check — claim_routes.py:352-360
- §2.8 item 20 — revise — **mismatch** — remand limit outranks the claim-state check — claim_routes.py:557-562
- §2.8 item 23 — revise — ambiguity — payments admit only `INVOICED`/`PARTIALLY_PAID`; surcharge filings only `NOT_STARTED` — funding.py:298-303, 348-353
- §2.9 — revise — ambiguity — duplicate coverage-profile line is `ERR_INVALID_REQUEST` — core.py:87-92
- §2.9 — insert — ambiguity — optional `statutory_deductible_cents` / `net_worth_exclusion_threshold_cents` must be ≥ 0 — core.py:63-70
- §3.1 — revise — ambiguity — duplicate insolvency `naic_code` is `ERR_INVALID_REQUEST`; `naic_code` is a free-form non-empty string — core.py:140-145
- §3.1 — revise — **mismatch** — trigger preconditions reordered: DECLARED → coverage profiles (any status) → IMPORTED policy (`ERR_INVALID_REQUEST`); no body fields — core.py:188-207
- §3.1 — insert — ambiguity — trigger and close both return the updated insolvency file; close takes no body — core.py:234, 385, 404
- §3.2 — revise — ambiguity — duplicate `receiver_batch_ref` is `ERR_INVALID_REQUEST` after the CLOSED gate; `records` elements must be objects and are echoed verbatim in every batch representation — core.py:431-445, domain.py:450
- §3.2 — revise — ambiguity — exact `MISSING_REQUIRED_FIELD` key sets per `record_type`; bad/absent `record_type` fails first; "empty" defined; optional fields default 0 / null `claim_number`; `UNKNOWN_LINE_OF_BUSINESS` applies to any element carrying a line including CLAIM; duplicate policy numbers resolve to earliest-created — core.py:497-621
- §3.2 — insert — ambiguity — conversion applies none of the direct-entry validations (no overlap, no duplicate claim, no date/state format, no filing deadline) and leaves insolvency `version` untouched; pass takes no body — core.py:548-586, 624-682
- §3.2 — revise — **mismatch** — `policy_number` need **not** be unique within an insolvency file (only term overlap is checked); the expiration-date failure is `ERR_INVALID_REQUEST` ahead of the CLOSED gate; four optional money fields must be ≥ 0 — policy_routes.py:46-83
- §3.3 — insert — ambiguity — refund `sequence` is monotone across every refund system-wide, not per policy — policy_routes.py:208
- §3.4 — insert — ambiguity — the named `policy_id` need not belong to the named `insolvency_id` — claim_routes.py:97-113
- §3.4 — revise — **mismatch** — settlement worksheet applies no adjuster ownership check, is status-agnostic, mixes stored claim terms with live config terms, `variant_delta_cents` = stored net − stored alt, null `cap_order_mode` with no profile — claim_routes.py:208-232
- §3.4 — revise — ambiguity — DENIED screening runs no payable computation, leaving all five computed terms 0 and `cap_binding` `NONE` — claim_routes.py:274-277
- §3.5 — insert — ambiguity — layer writes return the layer row; PURSUING keeps `recovered_cents` 0 even if supplied and does not bump the claim `version` — claim_routes.py:341-370
- §3.5 — revise — ambiguity — `recovered_cents` optional (0 when omitted), ≥ 0; stated-limit check applies to any target status and precedes both state checks — claim_routes.py:334-348
- §3.6 — revise — ambiguity — `hours` may be fractional, ≥ 0; wrong or non-`ASSIGNED` engagement gives `ERR_NOT_ASSIGNED_ADJUSTER`; `hours_logged` int-or-float; no invoice entity persisted and `invoice_ref` not stored; 201 returns the engagement — claim_routes.py:499-511, calc.py:240-248
- §3.7 — insert — **mismatch** — remand limit tested before the `RECOMMENDED` status check — claim_routes.py:557-562
- §3.7 — revise — ambiguity — `recommended_amount_cents` must be an integer ≥ 0 — claim_routes.py:525
- §3.8 — insert — ambiguity — referral create and respond both answer with the referral row (field list given); `response_note` null when omitted — claim_routes.py:661-676, 704-732
- §3.9 — revise — ambiguity — member amendment: omitted fields retained, empty payload still bumps `version`, gated on nothing but existence — funding.py:99-114
- §3.9 — revise — ambiguity — assessment `base_year` must be 2000-2100 — funding.py:145
- §3.9 — revise — ambiguity — payment `amount_cents` > 0; `PAID` and `DELINQUENT` refuse payments with `ERR_MEMBER_ASSESSMENT_INVALID_STATE` before the overpayment check, making delinquency terminal — funding.py:295-313
- §3.9 — insert — ambiguity — `RECOUPED` siblings excluded from the surcharge aggregate; `surcharge_rate_bps` bounded 0-300 and `surcharge_base_cents` ≥ 0 at shape, so a lone rate above 300 is `ERR_INVALID_REQUEST` — funding.py:342-364
- §3.9 — revise — ambiguity — `proceeds_cents` > 0 — funding.py:387
- §3.10 — revise — ambiguity — remittance `amount_cents` ≥ 0 (zero accepted, still bumps version); returns the insolvency file — core.py:243-249
- §3.10 — revise — ambiguity — `distribution_amount_cents` ≥ 0; a zero-funded run is accepted and still advances `distribution_sequence` and `version` — core.py:259, 363-365
- §3.10 — insert — ambiguity — items with zero outstanding are excluded from a class entirely, and an item allocated 0 cents is untouched, unversioned and omitted from the per-item detail — core.py:289-298, 304-305, 326-342
- §3.10 — revise — ambiguity — the run answers a bespoke 8-field payload; `claim_payments` entries are `{claim_id, allocated_cents, paid_amount_cents, status}` and `refund_payments` entries `{refund_id, …}`, in class order, empty when nothing paid — core.py:316-323, 354-378

Judgement calls I made and deliberately did **not** pin: the undeclared-route 404/405 → `ERR_INVALID_REQUEST` fallback (out of scope for declared endpoints), the `term <= 0` refund branch (unreachable given `expiration_date > effective_date`), and the `total_base == 0` allocation break (unreachable given the positive-premium eligibility filter). I also left §2.7's "fully recomputed on every write" language alone, since the implementation's derive-at-serialization counters are observationally equivalent.

Orchestrator verification of the final artifact: `workspace/PRD_COMPLETED.md` is 444 lines / 112,361 bytes and ends at a real section boundary (the final `| ERR_INSUFFICIENT_ESTATE_FUNDS | 422 |` row of the §5 catalogue), not mid-sentence. `diff` of the heading lists against `PRD_FINALIZED.md` is empty — no section was added, removed or renamed. §4 still carries 47 endpoint rows and §5 still carries 49 error rows. `diff` reports 38 hunks, matching the subagent's count.

## Pipeline complete — 2026-09-03T01:03:00.000Z

All nine steps finished. Final state of `tasks/task_2466_insurance_guaranty_association_insolvency_claims/`:
- `SCAFFOLD.yaml` (2617 lines), `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (1395), `SCAFFOLD_CORNER_DESIGN.yaml` (3496)
- `test_helpers/` (9 files, 2261 lines + the Step 7 `assert_instant_equals` addition), `test_suite/` (conftest + 17 test files, 122 tests, 122 `Design:` tags)
- `workspace/INSTRUCTION.md`, `workspace/PRD.md` (442 lines), `workspace/PRD_FINALIZED.md` (442), `workspace/PRD_COMPLETED.md` (444)
- `workspace/implementation/` (~3631 lines, 47 endpoints, in-memory only) plus `results.{1..8}.json`, all 122/122
- `worklog.md` (this file)
