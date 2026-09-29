# Worklog — task_2452_transplant_center_living_donor_evaluation_outcomes_reporting

## Step 1: Create task directory — 2026-09-02T19:58:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2452_transplant_center_living_donor_evaluation_outcomes_reporting` and its `workspace/` subdirectory. Index 2452 was pre-assigned by the invoking pipeline; no scan of `./tasks/` was performed and no other task directory was created.

## Step 2: Generate scaffold — 2026-09-02T22:18:30.000Z

All three scaffold artifacts are complete and the mandatory gate passes.

**Lint verdict block (verbatim):**

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2452_transplant_center_living_donor_evaluation_outcomes_reporting/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2452_transplant_center_living_donor_evaluation_outcomes_reporting/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2452_transplant_center_living_donor_evaluation_outcomes_reporting/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    54
  §1.1 entities declared:     14
  §1.8 instances scanned:     18
  §1.9 instances scanned:     116
  Calls scanned (§1.8+§1.9):  3064

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**Worklog summary**

Task 2452 — Transplant Center Living Donor Evaluation & Outcomes Reporting. `difficulty_level: expert_plus`, `api_prefix: ""`, graph topology, logical clock (`POST /_clock/set_current_utc`, forward-only, default `2026-08-01T00:00:00Z`), pagination limit/offset/total_count/has_more.

- `SCAFFOLD.yaml` (§1.0–§1.7, 187 KB): **14 entities** (TransplantProgram, StaffMember, OperatingRoom, RecipientCandidate, WaitlistStatusEvent, DonorCandidate, DonorEvaluation, ExchangeChain, ChainSegment, ProcedureBooking, DonorFollowUp, DonorCostClaim, ProgramOutcomeReview, ImprovementPlan); **54 endpoints** (33 POST / 21 GET); **65 error codes**; **15 calculations** (3 dual-variant: donor_risk_index, cold_ischemia_time, donor_cost_reimbursement); **24 validation priorities**; **13 state-machine dimensions** (DonorCandidate carries 4: overall/advocacy/medical/psychosocial); **6 roles** (ProgramAdmin, TransplantCoordinator, DonorAdvocate, EvaluationReviewer, QualityOfficer, FinanceAdmin); **2 concurrency rules** (chain-segment add, improvement-plan create).
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8, 165 KB): **9 rule_ids × 2 = 18 instances** (dual_variant_calc, combinatorial_formula, non_linear_state_machine, transitive_cascade, priority_pair_validation_conflict, boundary_precision_check, cross_entity_state_dependency, resource_temporal_overlap, compensating_invariant).
- `SCAFFOLD_CORNER_DESIGN.yaml` (§1.9, 884 KB): **137 instances = 116 full recipes + 21 `excluded_because` stubs**, in guide order — entities 11, state_machines 17, calculations 17, validations 9, endpoints 6, errors 65 (one per declared code), rbac 6, cross_cutting_complexity_layers 4, consistency_model 2.

Fixes made during the audit worth recording: (1) `ImprovementPlan.terminal_states` narrowed to `[SUPERSEDED, CLOSED]` (REJECTED is endpoint-terminal only, since a newer plan supersedes it); (2) all §1.5 path placeholders normalized from `{programId}`-style to `{id}` — `scaffold_lint.py` check (f) only recognizes the sub-resource reverse-reachability form when the parent segment is spelled `/{id}/`, and this was the sole source of 6 `FK_REVERSE_UNREACHABLE` violations (StaffMember, WaitlistStatusEvent, OperatingRoom, DonorFollowUp, ImprovementPlan, DonorCostClaim); (3) role grounds corrected from the non-existent `rbac.*` key to `roles.*`; (4) "simultaneously" removed from three `distinguishing_aspect` lines per the forbidden-concurrency-vocabulary checklist item.

Orchestrator verification: all three files present; `SCAFFOLD.yaml` contains neither design key (grep count 0).

## Step 3: Copy shared files — 2026-09-02T22:19:10.000Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-02T22:34:20.000Z

PRD generation for task_2452 is complete.

**Output:** `workspace/PRD.md` — **479 lines**, written in four Write/Edit passes anchored on a `<!--CONTINUE-->` sentinel (sentinel removed; verified absent).

**Section list (25 headings):**
- `# Transplant Living Donor Program API — Product Requirements Document`
- `## 1. Introduction`
- `## 2. Global Specifications & System-Wide Principles` — 2.1 Authentication, Center Personnel, and Role-Based Access Control · 2.2 API Response Structure · 2.3 Pagination · 2.4 Common Resource Properties and the Logical Clock · 2.5 Nested Path Resolution and Single-Program Containment · 2.6 Request Shape, Numeric Precision, and Rounding · 2.7 Optimistic Concurrency Control · 2.8 Compliance Posture: the Program-Wide Gate · 2.9 Cascade Discipline and Conservation Invariants · 2.10 Validation Ordering and the First-Violation Rule
- `## 3. Business Logic & Workflows` — 3.1 Standing Up a Program: Policy, People, and Theatres · 3.2 Recipient Candidacy and the Waitlist Ledger · 3.3 Donor Referral, Independent Advocacy, and the Cooling-Off Window · 3.4 Clinical Evaluation: Exclusion Screening, Determinations, and Risk Indices · 3.5 Building an Exchange Chain and Validating its Topology · 3.6 Commitment, Organ Offers, and Cold-Ischemia Logistics · 3.7 Realizing the Transplant and the Post-Donation Follow-Up Obligation · 3.8 Outcome Monitoring, Flagging, and Improvement Plans · 3.9 Donor Cost Coverage and the Program Fund
- `## 4. Endpoint Definitions`
- `## 5. Error Code Catalogue`

**Coverage (all verified mechanically against SCAFFOLD.yaml):**
- Endpoints: **54/54** rows in the §4 table (33 writes incl. the clock capability, 21 reads), each with method, path, description and authorized roles.
- Error codes: **65/65** rows in §5 with exact HTTP statuses; additionally all **65/65** appear in the §1–§4 prose, not only in the catalogue.
- Calculations: **15/15** expressed in prose, including the 3 dual-variant pairs (planned vs. actual cold ischemia, estimated vs. adjudicated reimbursement, and the per-component vs. sum-then-round priority score). Every numeric constant in every calculation is present in the text.
- Field names: **158/158** required identifiers (148 entity fields + 10 non-entity endpoint inputs) appear verbatim in backticks.
- Enum tokens: **79/79** present. State machines: **13/13** dimensions, **78/78** transitions, every from/to state present.
- Validation priorities: all **24** enumerated in §2.10 with error IDs, statuses, the four priority-8 exemptions, and exact `applies_to` scopes. OCC: both rules with write endpoint, `expected_chain_version`/`expected_review_version`, error ID and 412.
- §2.2 emitted byte-identically from `section-2.2-response-structure.md` (verified by substring match).

**Hard Contract results:** Contract 1 (field-name coverage) **PASS** — 0 missing, confirmed on two independent passes. Contract 2 (rule coverage) **PASS**. Contract 3 (§3 path purity) **PASS** — 0 backtick tokens in §3 start with `/`, are a bare HTTP method, or combine method+path.

**Tail check:** read the last 60 lines. The file ends at a real section boundary — the final row `| \`ERR_DONOR_LIFETIME_CAP_REACHED\` | 422 |` completing the §5 table, followed by a single terminating newline (four stray trailing blank lines were trimmed). No mid-sentence truncation, no audit footer. **Exact final section heading: `## 5. Error Code Catalogue`.**

**Constraint compliance:** neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped, or referenced; only `SCAFFOLD.yaml` and the skill files were read. Worked examples in the PRD were derived independently from the scaffold's own formulas and boundary semantics.

**Orchestrator-side truncation guard (independent re-check, per invocation instructions):** `wc -l` = 479; `tail -25` ends on the complete table row `| \`ERR_DONOR_LIFETIME_CAP_REACHED\` | 422 |`, a real section boundary at the close of §5, not mid-sentence; `grep -n "^## "` confirms all five top-level sections present in order (1 Introduction @3, 2 Global @11, 3 Business Logic @180, 4 Endpoints @350, 5 Errors @411). No regeneration needed. Also grepped PRD.md for `harder than expert` / `expert_plus` / `expert level` / `scaffold` — zero hits, so the Step 2-only difficulty instruction did not leak into the PRD.

## Step 6: Generate implementation — 2026-09-02T23:31:00.000Z

Note: this step's subagent was interrupted once by a transient upstream API error ("The system encountered an unexpected error during processing") after writing calc/db/domain/errors/middleware/response/serialize/util/validation and routes/{programs,recipients,donors,evaluations}.py but before app.py existed. The orchestrator resumed the same agent via SendMessage (context intact) rather than respawning a fresh one, so no work was redone; the summary below is from the resumed agent's completion.

Implementation complete and verified. Stray verification server (port 18460) has been shut down; the 8 concurrent `app.py` processes belonging to the other in-flight agent were left untouched.

## Task 2452 — Flask implementation summary

**Files written** (all under `workspace/implementation/`, 21 files, ~4,300 lines of Python):

| File | Role |
| --- | --- |
| `start.sh` | launcher (guarded `pip install`, then `exec python3 app.py`) |
| `requirements.txt` | `Flask>=2.2.0` |
| `app.py` | app factory, registers 9 blueprints, `ApiError`/`HTTPException`/`Exception` handlers |
| `db.py` | in-memory `Store` (14 dicts), logical clock, `new_entity`/`new_event`/`touch` |
| `errors.py`, `response.py`, `middleware.py`, `validation.py` | `ApiError`, envelope + pagination meta, `X-User-Id`/`X-User-Role` auth, 24-priority validation helpers |
| `util.py`, `calc.py`, `domain.py`, `serialize.py` | Decimal/ROUND_HALF_UP helpers, all formulas, cross-entity derivations + posture/status refresh, 14 serializers |
| `routes/programs.py` | programs, staff, rooms, compliance sweep, `POST /_clock/set_current_utc` |
| `routes/recipients.py` | recipient candidates, status updates, waitlist events |
| `routes/donors.py` | donor candidates, advocate assignment, consent disclosure, advocacy determination |
| `routes/evaluations.py` | donor evaluations, determination, resubmission |
| `routes/chains.py` | exchange chains, segments, validation/commitment/break, offer, offer-response, transplant-completion (681 lines) |
| `routes/bookings.py` | procedure bookings + cancellation (OR turnover-buffer and surgeon-overlap rules) |
| `routes/followups.py` | follow-up submission + waiver |
| `routes/reviews.py` | outcome reviews, finalization, improvement plans + transitions |
| `routes/claims.py` | donor cost claims, adjudication waterfall, reversal |

**Endpoint count: 54 implemented (33 POST, 21 GET).**

**url_map verification (the requested check):** booted the app, enumerated `app.url_map`, normalised path params, and diffed against the PRD §4 endpoint table. Result: `impl 54 / prd 54`, `POST 33 / GET 21`, **missing from impl: [] — extra in impl: []**. No import errors; `routes/` works as an implicit namespace package.

**`start.sh` confirmation:** reads the port via `app.py`'s `int(os.environ.get("PORT", "10000"))`, binds `host="0.0.0.0"` (`threaded=True, use_reloader=False`), and runs in the foreground via `exec python3 app.py`. A fresh boot logged ` * Running on all addresses (0.0.0.0)` / `http://127.0.0.1:<PORT>`.

**Storage / seeding:** in-memory dicts only — a repo-wide grep for `sqlite|open(|json.dump|pickle|/tmp` across the implementation returns nothing. Confirmed on a brand-new process that every collection reports `total_count: 0` and the logical clock reads exactly `2026-08-01T00:00:00Z`, so each `--isolation per-test-server` relaunch starts from an empty world.

**Behavioural smoke tests (`FAILURES: 0`)** built the entire domain from the empty store through declared endpoints only: program/staff/rooms → 2 ACTIVE recipients → 2 APPROVED donors (advocate → disclosure → both evaluations CLEARED → +9d → ATTESTED) → 2-segment PAIRED_LOOP (closed loop, `committed_donor_count` 2) → 412 on a stale `expected_chain_version` → bookings (duration 240, reserved 420, 409 surgeon double-book) → offer (`planned_cit` 345, deadline +6h) → ACCEPT → transplant completion (actual CIT 300, no breach, donor DONATED, recipient TRANSPLANTED with a `TRANSPLANT_COMPLETED` waitlist event, chain EXECUTING) → 3 follow-ups at +180/+365/+730d (422 `ERR_FOLLOW_UP_NOT_DUE`, then 83.33 → `SUBMITTED_COMPLETE`, plus a waiver) → LOST_WAGES claim matching the PRD's weekly-cap worked example (150000) → adjudication → reversal → outcome review (expected 19.0, O/E 0.7895, FLAGGED) → finalization → posture FROZEN → plan ACCEPT → posture OPEN → manual chain break (BROKEN, `committed_donor_count` 0, surviving donor released to APPROVED). A second script confirmed 400 on `limit=0/101`, `offset=-1` and bad enums, 200-with-0-rows for unknown FK filters, 422 `ERR_CLOCK_NOT_MONOTONIC`, 404 `ERR_NOT_FOUND`, 405 `ERR_METHOD_NOT_ALLOWED`.

Scope constraints respected: nothing under `test_suite/`, `test_helpers/`, `SCAFFOLD_DIFFICULTY_DESIGN.yaml` or `SCAFFOLD_CORNER_DESIGN.yaml` was read.

## Step 5: Generate unit tests — 2026-09-03T02:38:00.000Z

Queue B is now complete; the whole suite re-verified against the correct PRD.

## Files written (this session)

- `test_suite/test_06c_errors_domain_rules.py` — 23 tests, the remaining `errors` instances: cooling-off, hard exclusion, donor not approved/committed/donated, cross-program containment, the six chain-topology codes (too short, non-contiguous, linkage broken, duplicate participant, loop not closed, NDD start), donor/implant booking missing, predecessor timing, offer window expired, follow-up not due, effective_at out of order, clock not monotonic, per-segment CIT limit (1081 refused, 1080 accepted on retry), chain CIT budget (2160 + 1080 vs 2400), plan not required, donor lifetime cap (1,000,000 + 350,000 + 150,000 = exactly 1,500,000, fourth claim refused at zero headroom).
- Earlier in the same queue-B block: `test_06a_errors_auth_and_existence.py` (18) and `test_06b_errors_state_and_conflict.py` (17).

## Final counts

- Queue A (Difficulty): 18 instances, 0 stubs, **40 tests**, every instance >= 2 tests, no bogus tags.
- Queue B (Corner): 137 instances of which 21 are `excluded_because` stubs -> 116 non-stub, **116 tests**, exactly 1 per instance, all sections 100 % covered (`entities 11/11, state_machines 13/13, calculations 10/10, validations 6/6, endpoints 6/6, errors 58/58, rbac 6/6, cross_cutting 4/4, consistency_model 2/2`).
- Total **156 tests**, 537 PRD citations, 0 citation defects, 0 untagged/dual-tagged/bogus tags, 0 stubs with tests, no `pytest.mark.skip`/`xfail` anywhere. All 21 stub `excluded_because` notes resolve to a real difficulty rule or instance name. All test modules import cleanly (so every helper referenced actually exists in `test_helpers/`).

## Instances skipped

None in this final block — all 23 remaining `errors` instances passed the PRD-first two-condition filter. Two design assertions were deliberately not translated because the PRD does not uniquely derive them: `err_donor_not_approved`'s "`is_closed_loop` null" (§3.5 says a new chain starts with `is_closed_loop` false and insertion recomputes it) and `err_follow_up_not_due`'s nullity assertions on `submitted_field_count`/`completeness_pct`. `err_duplicate_npi` asserts a role-filtered empty listing plus overall total 1 rather than the design's fixture-specific `total_count == 4`.

## Tooling finding worth noting

`/tmp/check_citations.py` (used earlier in this task) had its `PRD` constant pointing at **task_2463**'s PRD — almost certainly clobbered by a concurrent agent on the shared host — so the previously reported "448 citations, 0 not verbatim" was checked against the wrong contract. I rewrote a task-scoped checker at `/tmp/check_citations_2452.py` and re-ran it over all 20 test files: only 5 real defects surfaced (all in the new `test_06c`, all §2.10 priority-item quotes paraphrased or under 8 words). They are fixed; the suite now reports 537/537 citations verbatim against `workspace/PRD.md`. Nothing under `workspace/implementation/` was read or written at any point.

Orchestrator note: Steps 5 and 6 were launched concurrently in a single assistant message, so the implementation generator started before `test_suite/` existed on disk — physical isolation held.

## Step 7: Run tests and iterate — 2026-09-03T03:20:00.000Z

All 8 rounds green.

## Summary

**Iterations run:** 2 (each an 8-round parallel `per-test-server` sweep).

**Iteration 1 result:** 150/156 in all 8 rounds, with the identical 6 failures every round (fully deterministic — a `grep FAILED` over the interleaved `sweep.log` showed 11 "names" only because 8 concurrent pytest processes shear each other's lines; `results.*.json` is the only reliable source).

**Tests deleted:** none — every failure was an assertion/payload defect inside an otherwise PRD-covered test, so STEP 1c (partial coverage) applied and only the uncovered assertion was removed.

**Assertions removed under STEP 1c (PRD-silence category per assertion):**
- `test_suite/test_02_state_machines.py::test_removing_a_recipient_withdraws_only_its_own_segment_and_breaks_the_chain` — dropped `segment_one["status"] == "PLANNED"` ("the cascade is selective and spares the sibling segment"). BRANCH-ASYMMETRIC SIDE EFFECT / not uniquely derivable: §3.2 hop 2 says the cascaded break "dragg[s] its own compensating cascade behind it", and §3.6 states verbatim that breaking "moves every non-withdrawn segment whose status is `PLANNED`, `OFFER_SENT` or `ACCEPTED` to `WITHDRAWN`" — so a faithful reader can equally conclude the sibling *is* withdrawn. Every other assertion (segment_two WITHDRAWN, chain BROKEN + `RECIPIENT_REMOVED`, `committed_donor_count == 0`, both donors back to APPROVED, 3 waitlist events, recipient_two still ACTIVE, `active_days_total == 7`) was kept.
- `test_suite/test_05_endpoint_behaviour.py::test_denying_a_claim_records_the_reason_and_moves_no_money` — dropped `denied["decision_reason_code"] == "NOT_DONOR_RELATED"`. RESPONSE-FIELD SILENCE: §3.9 requires the input `decision_reason_code` on a denial but never declares it as a claim attribute; the claim's own null-on-creation list is `adjudicated_reimbursement_cents`, `unfunded_cents`, `adjudicated_at`, `adjudicated_by_user_id`, `reversal_reason_code` — `decision_reason_code` is absent. All money/status/timestamp assertions kept.
- `test_suite/test_06b_errors_state_and_conflict.py::test_err_follow_up_terminal_returns_409` — dropped `reread["completeness_pct"] is None`. DEFAULT-VALUE SILENCE: §3.7 defines `completeness_pct` only as a computed result of a submission; nothing states its value on a never-submitted or waived row (impl reports 0.0). The `ERR_FOLLOW_UP_TERMINAL` check, `status == WAIVED`, `submitted_at is None`, `waiver_reason_code` and the vacuous `follow_up_compliance_pct == 100.0` were kept.
- `test_suite/test_06c_errors_domain_rules.py::test_err_implant_booking_missing_returns_422` — dropped `after["cit_breach"] is None`. DEFAULT-VALUE SILENCE: §3.7 only says `cit_breach` is set true/false *at completion*; §3.5's "every offer and planning field null" does not cover a completion flag (impl reports `false`). The `ERR_IMPLANT_BOOKING_MISSING` check plus `status == ACCEPTED`, `actual_cit_minutes is None`, `planned_cit_minutes == 405`, donor still `CHAIN_COMMITTED` were kept.

**Fixes applied to `test_helpers/`:**
- `test_helpers/fixtures.py`, `setup_offered_segment` / `setup_accepted_segment` / `setup_donated_donor` — made stage-aware. The `env = env or <build_previous_stage>()` idiom silently *skipped* every intermediate stage when a caller passed a pre-built env, so `setup_donated_donor(env)` on a merely-COMMITTED loop tried to complete a still-`PLANNED` segment and the PRD-correct implementation refused with `ERR_INVALID_STATE_TRANSITION`. Each helper now short-circuits if `segment_one` is already at its target status and otherwise advances the missing stages (and reuses an existing `segment_one_bookings` rather than double-booking).

**Fixes applied to `test_suite/` (request faithfulness, STEP 2):**
- `test_suite/test_06b_errors_state_and_conflict.py::test_err_review_not_finalized_returns_409` — the plan transition was posted as `{"action": "ACCEPT"}` with no `decision_reason_code`. §3.8 ("A `ProgramAdmin` acts on a plan by supplying an `action` and, for a decision, a `decision_reason_code`" / "Accepting … records the reason code") plus §2.6's required-reason-code list make that a priority-4 `ERR_VALIDATION`, which correctly pre-empts the priority-9 gate under §2.10. Added `"decision_reason_code": "PLAN_SATISFACTORY"` so the request reaches the gate the test is about.

**Fixes applied to `implementation/`:** none. Every failure traced to the test artifact; no PRD-required check was removed or weakened, and no endpoint/field/side-effect was added.

**Final sweep evidence (iteration 2, 8 concurrent rounds under `setsid nohup`):**
- results.1.json — 156/156
- results.2.json — 156/156
- results.3.json — 156/156
- results.4.json — 156/156
- results.5.json — 156/156
- results.6.json — 156/156
- results.7.json — 156/156
- results.8.json — 156/156

(0 failed, 0 errors, 0 skipped in every round; no `pytest.mark.skip`/`xfail` introduced anywhere.)

**Orchestrator independent verification (per the known Step-7 failure mode where a subagent reports a clean sweep without leaving artifacts):** parsed all 8 `results.*.json` myself — each reports `passed=156 total=156 failed=0 errors=0 skipped=0`, all eight written at the same wall-clock second (00:48:49), consistent with a genuine concurrent 8-round sweep rather than a serial replay. Grepped `test_suite/` and `test_helpers/` for `pytest.mark.skip`/`xfail`: none present. Step 8 is NOT skipped — Step 7 applied 1 `test_helpers/` fix, 1 `test_suite/` payload fix and 4 STEP-1c assertion removals (only the "0 implementation fixes" leg of the skip condition is satisfied), so the PRD silences those items expose still need pinning.

## Step 8: Finalize PRD — 2026-09-03T04:00:00.000Z

`PRD_FINALIZED.md` is written. Report follows.

## Line counts
- `PRD.md`: 479 lines / 103,816 chars
- `PRD_FINALIZED.md`: 479 lines / 105,598 chars
- **%-delta: 0.0% lines (6 of 479 paragraph-lines revised, +1.72% characters)**. No sections added, no prose deleted.

## Changes (one bullet each)
- **§3.2 (recipient removal cascade, hop 2)** — *revise* — appended a clause pinning that the cascading break is **not** selective: it also withdraws the chain's other remaining `PLANNED`/`OFFER_SENT`/`ACCEPTED` segments, including ones naming a different recipient, releases the chain's committed donors, zeroes `committed_donor_count` and cancels its `ACTIVE` bookings — `implementation/domain.py:398-437` (`break_chain` / `cascade_participant_withdrawal`), reached from `implementation/routes/recipients.py:169`.
- **§3.5 (segment insertion defaults)** — *revise* — pinned the realized fields (`actual_cross_clamp_at`, `actual_reperfusion_at`, `actual_cit_minutes`) as null and `cit_breach` as **false** (not null) on a freshly inserted segment, staying false until a completion evaluates it — `implementation/routes/chains.py:194-197`, `implementation/routes/chains.py:638`.
- **§3.7 (donation cascade, follow-up row creation)** — *revise* — pinned each new follow-up row's creation values: `submitted_field_count` 0, `completeness_pct` 0 (a zero figure, not null), `submitted_at` and `waiver_reason_code` null — `implementation/domain.py:445-466` (`create_follow_ups`, `completeness_pct: Decimal("0")`).
- **§3.7 (Delinquency and waiver)** — *revise* — pinned that waiver leaves `submitted_field_count`, `completeness_pct` and `submitted_at` untouched, so a never-submitted waived row reports `submitted_at` null and `completeness_pct` 0 while a row waived after an incomplete submission keeps that submission's figures — `implementation/routes/followups.py:82-84`.
- **§3.8 (Deciding a plan)** — *revise* — pinned that `decision_reason_code` is required for `ACCEPT` and `REJECT` (absence = priority-4 `ERR_VALIDATION`, pre-empting the review-not-finalized gate) and not required for `CLOSE`, which neither records nor clears the plan's existing code — `implementation/routes/reviews.py:249-282`.
- **§3.9 (denial)** — *revise* — pinned that a claim's denial `decision_reason_code` is a decision input only: no claim attribute, not stored, not present in the returned claim representation — `implementation/routes/claims.py:109-139`, `implementation/serialize.py:271-293`.

## Per-edit pre-edit search log

**Edit 1 — §3.2 cascading break selectivity**
- (a) Subject: which segments a chain break withdraws when the break arrives as a cascade from a lost participant (sibling-segment fate).
- (b) Paths enumerated/read: `domain.cascade_participant_withdrawal` (domain.py:425-437) and its three callsites — `routes/recipients.py:169` (recipient `REMOVED`), `routes/donors.py:328` (advocate objection), `routes/evaluations.py:233` (donor exclusion); `domain.break_chain` (domain.py:398-419) and its two direct callsites — `routes/chains.py:385` (caller-driven break) and `routes/chains.py:581` (`DONOR_ORGAN_QUALITY` decline); `domain.chain_committed_donor_count` (domain.py:227-236); `domain.refresh_donor_status`/`derive_donor_overall_status` (domain.py:270-300); `_suspend_chains_for_freeze` (domain.py:367-384, the *other* cascade that clears offer fields but does **not** withdraw segments); PRD §3.6 break prose, §3.3 objection cascade, §3.4 exclusion cascade.
- (c) Adjustment: wrote the clause as an explicit cross-reference to §3.6's break rather than as new local behavior, so §3.3's and §3.4's cascades (same code path) are not narrowed or contradicted; enumerated the withdrawal set as exactly `PLANNED`/`OFFER_SENT`/`ACCEPTED` (not "all live segments") so `TRANSPLANTED` and `DECLINED` segments, which `break_chain` leaves alone, are not mis-described; summarised donor release as "releases the chain's committed donors" instead of naming target statuses, since §3.6 already pins the `APPROVED`/`CONDITIONAL_APPROVED` split by `final_risk_index`.

**Edit 2 — §3.5 `cit_breach` / realized-field defaults**
- (a) Subject: initial value of `cit_breach` and the actual-cold-ischemia fields on a segment that has never been completed.
- (b) Paths enumerated (grepped `cit_breach` repo-wide): `routes/chains.py:177-199` (insertion, `"cit_breach": False`), `routes/chains.py:632-639` (completion sets it from `actual_cit > 1080`), `routes/chains.py:669` (breach-driven posture re-derive), `domain.program_cit_breach_count` (domain.py:165-171, counts truthy flags), `serialize.chain_segment` (serialize.py:196, passthrough), `domain.OFFER_FIELDS_TO_CLEAR` + `_suspend_chains_for_freeze` (domain.py:357-384) and `routes/recipients.py:161-167` (`INACTIVE_HOLD` revert) — both clear offer/planning fields only and never touch `cit_breach` or the actual timestamps; `break_chain` (no reset); re-offer path `routes/chains.py:521-531` (no reset).
- (c) Adjustment: scoped "stays false until a transplant completion evaluates it" rather than "is false unless breached", because completion legitimately writes `false` too; explicitly separated `cit_breach` from the "offer and planning field null" list so the freeze/hold clearing cascades (which do not clear it) stay consistent.

**Edit 3 — §3.7 follow-up creation defaults**
- (a) Subject: field values a follow-up row holds between creation and its first submission.
- (b) Paths enumerated (grepped `completeness_pct`, `submitted_field_count`): `domain.create_follow_ups` (domain.py:445-466 — `submitted_field_count` 0, `completeness_pct` `Decimal("0")`, `submitted_at`/`waiver_reason_code` null, `required_fields_count` per interval); `routes/followups.py:51-61` (submission overwrites count/pct/`submitted_at`); `routes/followups.py:82-84` (waiver touches status + reason only); `routes/programs.py:111-115` (sweep touches status only); `calc.compliance_pct` via `domain.program_compliance_pct` (uses status + `due_on`, never `completeness_pct`); `serialize.donor_follow_up` (serialize.py:218-232) and its readers `routes/followups.py:64,87` + `routes/donors.py:137` (listing uses the same serializer, so the pinned defaults hold on the list endpoint too); `util.num` (util.py:76-82, Decimal->float, so the value renders as a zero number).
- (c) Adjustment: wrote "`completeness_pct` 0 — a zero figure, not null" rather than "0.00" so no formatting/precision claim is made beyond the numeric value; kept the statement to *creation* values so the submission path that overwrites them is untouched.

**Edit 4 — §3.7 waiver leaves figures alone**
- (a) Subject: what the waiver transition does and does not write on a follow-up row.
- (b) Paths enumerated: `routes/followups.py:67-87` (waiver: status, `waiver_reason_code`, `touch`, `refresh_posture` — nothing else); `routes/followups.py:29-64` (the only writer of `submitted_field_count`/`completeness_pct`/`submitted_at`); `routes/programs.py:105-120` (sweep: `DUE`/`INCOMPLETE` -> `DELINQUENT` only); `domain.create_follow_ups`; `calc.compliance_pct` (a `WAIVED` row leaves both numerator and denominator, so this edit cannot perturb the compliance figure).
- (c) Adjustment: covered both entry paths (waived-from-`DUE` and waived-from-`INCOMPLETE`) so the sentence does not assert 0/null universally for `WAIVED` rows — a row waived after an incomplete submission retains non-zero figures in the implementation.

**Edit 5 — §3.8 which plan actions require `decision_reason_code`**
- (a) Subject: presence requirement and persistence of `decision_reason_code` across the three plan actions.
- (b) Paths enumerated: `routes/reviews.py:243-285` (`opt_str` read; `ERR_VALIDATION` only for `ACCEPT`/`REJECT`; the code is written on `ACCEPT` and `REJECT`; the `CLOSE` branch writes `closed_at` only and leaves the existing `decision_reason_code` in place); `routes/reviews.py:223-235` (creation nulls it); `serialize.improvement_plan` (serialize.py:255-268, plan *does* expose it — contrast with the claim in Edit 6); `calc.PLAN_ACTIONS`; PRD §2.6 required-reason-code list, §2.10 priority 4 vs priority 9.
- (c) Adjustment: phrased the close case as "neither requires the code nor records or clears whatever code the plan already carries", because a plan closed after acceptance keeps the acceptance's reason code — "closing does not record a reason code" alone would have implied a null.

**Edit 6 — §3.9 claim denial `decision_reason_code` not a claim field**
- (a) Subject: persistence and exposure of the adjudication `decision_reason_code` on a donor cost claim.
- (b) Paths enumerated: `routes/claims.py:102-163` (read via `opt_str`, required for `DENY`, never assigned to the claim row on either branch); `routes/claims.py:76-97` (creation field set — no `decision_reason_code` key); `routes/claims.py:166-186` (reversal writes `reversal_reason_code` only); `serialize.donor_cost_claim` (serialize.py:271-293 — field absent) and all four of its callers (`routes/claims.py:99,139,163,186`) plus the donor-scoped listing `routes/donors.py:155`; contrasted with `serialize.improvement_plan` (serialize.py:264), which *does* expose a `decision_reason_code`.
- (c) Adjustment: scoped the sentence explicitly to the claim ("a claim has no `decision_reason_code` attribute of its own") so it cannot be read as a system-wide statement that would contradict the improvement plan's own persisted `decision_reason_code`; also split the run-on so the denial's other side effects read unchanged.

**No PRD edit made for:** the `test_helpers/fixtures.py` stage-awareness fix (pure fixture defect — the implementation's `ERR_INVALID_STATE_TRANSITION` on completing a still-`PLANNED` segment is already pinned by §3.7's "only reachable from `ACCEPTED`") — verified against `routes/chains.py:605-610`.

## Step 9: Complete PRD — 2026-09-03T04:20:00.000Z

All 31 pins are applied and verified. Here is the exit summary.

**PRD_COMPLETED.md — verification**
- `PRD_FINALIZED.md`: 479 lines, 105,598 chars
- `PRD_COMPLETED.md`: 479 lines, 111,569 chars (**char delta +5,971; line delta 0**)
- `diff` reports 29 changed lines, 0 added/removed lines — no section, table row or paragraph lost.
- Tail check passes: file still ends `| \`ERR_CHAIN_CIT_BUDGET_EXCEEDED\` | 422 | / | \`ERR_PLAN_NOT_REQUIRED\` | 422 | / | \`ERR_DONOR_LIFETIME_CAP_REACHED\` | 422 |`.

**Counts:** 31 changes total — **25 ambiguity-pins**, **6 mismatch-revisions** (Step 8's six sites were left untouched).

**Changes**
- §2.2 — insert — ambiguity — `api_request_id` is `req_` + sixteen lowercase hex chars — response.py:13
- §2.2 — insert — ambiguity — `api_request_timestamp` is wall-clock, not the §2.4 logical clock — response.py:14
- §2.3 — insert — ambiguity — `created_at` ties (the common case) break by ascending creation order — db.py:104-106
- §2.4 — insert — ambiguity — a row's `version` advances at most once per request; an unchanged re-write doesn't advance it — db.py:88-101
- §2.4 — insert — ambiguity — clock-set answers 200 with empty `data`; setting to the current reading is accepted — programs.py:227-235
- §2.5 — revise — mismatch — replaced "every write endpoint that accepts more than one foreign key" with the nine endpoints that actually run it, the acting staff `program_id` joining the set on eight of them, and the three endpoints that compare nothing — donors.py:50-56, evaluations.py:109, chains.py:63 & 157-167, bookings.py:57-64, reviews.py:70 & 207, claims.py:68
- §2.8 — insert — ambiguity — unchanged posture writes nothing and doesn't move `version`; clock advance alone re-derives nothing — domain.py:342-354
- §2.9 — insert — ambiguity — cascade `touch` is once-per-row however many hops reach it — db.py:88-101
- §2.9 — insert — ambiguity — fund ledger is read-time derived, so adjudication/denial/reversal never writes the program row — serialize.py:32-33, claims.py:154-162
- §2.10 item 8 — insert — ambiguity — priority 8 also carries the donor `overall_status` bars, the `CHAIN_COMMITTED` cleared-dimension bar and the `TRANSPLANTED`-segment cancellation bar — donors.py:173-182 & 235-250, evaluations.py:198-206 & 261-265, bookings.py:121-125
- §2.10 item 20 — insert — ambiguity — predecessor-timing runs before the booking-existence checks — chains.py:477-497
- §3.2 — insert — ambiguity — `medical_urgency_points` is an unbounded integer — recipients.py:59
- §3.2 — insert — ambiguity — `to_status` enum is the six non-`WORKUP` statuses; `WORKUP` fails at priority 4, `TRANSPLANTED` at priority 8 — recipients.py:32-37,127
- §3.3 — insert — ambiguity — advocate assignment is one-shot; a second attempt is `ERR_INVALID_STATE_TRANSITION` — donors.py:178
- §3.3 — insert — ambiguity — `outcome` enum is `ATTESTED`/`OBJECTED` — calc.py:115, donors.py:276
- §3.4 — insert — ambiguity — the four medical measurements are all required and carry no declared range — evaluations.py:59-62
- §3.4 — insert — ambiguity — the three psychosocial booleans are read and defaulted on both domains, never nulled — evaluations.py:47-57
- §3.4 — revise — mismatch — the reviewer is the authenticated caller, so priority 2 returns `ERR_UNAUTHORIZED` and `ERR_STAFF_ROLE_INVALID` is unreachable here — evaluations.py:94
- §3.5 — insert — ambiguity — insertion accepted in DRAFT/VALIDATED/SUSPENDED/COMMITTED/EXECUTING; only COMPLETED/BROKEN refuse — chains.py:150
- §3.5 — insert — ambiguity — `predecessor_segment_id` need only be an existing same-program segment at insertion — chains.py:137-139
- §3.5 — revise — mismatch — participant eligibility is described last but judged first (priority 14 before 16), donors before recipients — chains.py:301-303, 212-228
- §3.6 — insert — ambiguity — `planned_transport_minutes` required, non-negative whole minutes — chains.py:441
- §3.6 — insert — ambiguity — planned reperfusion-after-clamp is priority-4 `ERR_VALIDATION`; a null predecessor `planned_reperfusion_at` imposes no constraint — chains.py:442, 479
- §3.6 — insert — ambiguity — `response` enum is `ACCEPT`/`DECLINE` — calc.py:134, chains.py:547
- §3.7 — insert — ambiguity — realized reperfusion-after-clamp is priority-4 `ERR_VALIDATION` — chains.py:599
- §3.7 — insert — ambiguity — `due_on` is a full instant carrying `donated_at`'s time of day, rendered ISO 8601 with 3 fractional digits — domain.py:453, serialize.py:224
- §3.7 — revise — mismatch — `submitted_field_count` counts distinct non-empty strings with no required-name vocabulary; list required but may be empty (-> 0.00, `INCOMPLETE`) — calc.py:317-322, followups.py:35
- §3.8 — revise — mismatch — superseding of SUBMITTED/REJECTED siblings is unconditional; an ACCEPTED/CLOSED plan neither blocks nor is moved — reviews.py:218-221
- §3.8 — insert — ambiguity — `action` enum is `ACCEPT`/`REJECT`/`CLOSE` — calc.py:142, reviews.py:249
- §3.9 — insert — ambiguity — `decision` enum is `APPROVE`/`DENY` — calc.py:146, claims.py:108
- §4 — revise — mismatch — waitlist-events listing is `effective_at` ascending with append-order ties, not append order — domain.py:141

**Module coverage tally (19 impl files, all walked)**
`app.py` 0 changes · `db.py` 3 · `util.py` 0 (already pinned by §2.6) · `errors.py` 0 · `response.py` 3 · `middleware.py` 0 (§2.1/§2.10 already exact) · `validation.py` 0 (§2.3/§2.6 already exact) · `serialize.py` 3 (shared anchors) · `calc.py` 5 (enum vocabularies + field count) · `domain.py` 5 · `routes/programs.py` 1 · `routes/recipients.py` 2 · `routes/donors.py` 3 · `routes/evaluations.py` 4 · `routes/chains.py` 8 · `routes/bookings.py` 2 (shared anchors; room/surgeon interval rules already exact) · `routes/followups.py` 1 · `routes/reviews.py` 2 · `routes/claims.py` 3.

No remaining silence or mismatch was found in the areas I deliberately re-checked and left alone: the §2.6 rounding/precision rules, the §2.7 concurrency ordering, the §2.8 posture derivation and cascade, the three §2.9 conservation invariants, the §3.3 cooling-off arithmetic, the §3.4 risk indices, the §3.5 ABO/loop/NDD topology rules, the §3.6 CIT ceilings and room/surgeon occupancy asymmetry, the §3.7 compliance formula, the §3.8 flag thresholds and cohort floor, and the §3.9 estimate cap and adjudication waterfall — all already match the implementation exactly.

**Orchestrator final verification:** `PRD.md` 479 lines / 103,816 chars; `PRD_FINALIZED.md` 479 lines / 105,598 chars; `PRD_COMPLETED.md` 479 lines / 111,569 chars — no line lost across either patch generation. `PRD_COMPLETED.md` still carries all 5 top-level sections and ends on the complete final §5 table row `| \`ERR_DONOR_LIFETIME_CAP_REACHED\` | 422 |`. Grep for `scaffold` / `harder than expert`: no hits, so the Step-2-only difficulty instruction never leaked into any PRD variant.

## Pipeline complete — 2026-09-03T04:22:00.000Z

All nine steps finished. Final state: 3 scaffold artifacts, 3 PRD variants (PRD.md -> PRD_FINALIZED.md -> PRD_COMPLETED.md), 8 test_helpers modules, 20 test_suite modules holding 156 tests, a 21-file Flask implementation serving 54 endpoints, and 8 stability-sweep result files each recording 156/156.
