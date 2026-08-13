# Worklog — task_1485_scholarship_search_award_matching

## Step 1: Create Task Directory — 2026-08-13T12:32:00.000Z

Task directory `tasks/task_1485_scholarship_search_award_matching/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline launcher. Step 1 treated as DONE per orchestration instructions.

## Step 2: Generate Scaffold — 2026-08-13T14:19:00.000Z

Scaffold generation complete. All three artifacts written to `/home/ubuntu/github/CodingPRD/tasks/task_1485_scholarship_search_award_matching/` with a clean lint verdict.

**Files written**
- `SCAFFOLD.yaml` — 1872 lines (§1.0–§1.7 only; no difficulty/corner keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 1558 lines (single top key `scaffold_difficulty_design`)
- `SCAFFOLD_CORNER_DESIGN.yaml` — 3318 lines (single top key `scaffold_corner_design`)

**Structural counts**
- Entities: 15 (Student, Donor, AwardFund, ScholarshipProgram, Application, ApplicationComponent, Reminder, ReviewCycle, ReviewScore, Award, Disbursement, AwardAdjustment, RenewalEvaluation, ThankYouLetter, DonorReport) — flat topology, every FK has a reverse-reachability GET
- State machines: 13 machines, 68 transitions (cycles on Application/ReviewCycle/ReviewScore/Disbursement/RenewalEvaluation/ThankYouLetter/DonorReport/Program-extend; parallel dimensions offer_status × funding_status on Award)
- Calculations: 10 rules, 3 with explicit variants (STRICT/HOLISTIC eligibility, ANNUAL/PER_TERM stacking caps, pinned disbursement split)
- Endpoints: 87 declared in §1.5 (incl. `/_clock/set_current_utc` with the mandatory 2026-08-01T00:00:00Z default and `/_ops/run_daily` ops checkpoint)
- Errors: 30; Validations: 12 ordered priorities; Roles: 6 (segregation-of-duties model; Student/Donor entity-backed); OCC concurrency rules: 3 (program edit, fund commitment, award patch)

**Difficulty tier**: maximum (beyond Expert band top: 15 entities, 30 error codes, 13 machines). Archetypes: multi-party negotiation (committee cycles) × compliance/audit (maker-checker on adjustments, sender≠confirmer on disbursements).

**§1.8 coverage audit** — 19 instances, all 9 rules ≥2:
dual_variant_calc 2 (eligibility policy domain vs stacking-cap fiscal domain), combinatorial_formula 2 (mode (a) tiered weighted ranking + mode (b) pinned rounding order), non_linear_state_machine 3 (Application cycle, Award parallel dimensions, ReviewCycle reopen loop), transitive_cascade 2 (confirm→Award→ThankYou→Report depth-3; accept→Student→auto-Adjustment depth-2), priority_pair_validation_conflict 2 (state-vs-temporal; safety-vs-fiscal), boundary_precision_check 2 (GPA 249/250 integer threshold; submit at exact close_at), cross_entity_state_dependency 2 (Application→Program; Disbursement→Award), resource_temporal_overlap 2 (half-open cycle windows vs closed disbursement terms), compensating_invariant 2 (fund money conservation; application-count conservation). All formula asserts pre-computed (e.g., 90.00/0.00, −500000, [333334, 333333, 333333], 83.00).

**§1.9 coverage audit** — 61 active instances + 9 `excluded_because` stubs across sections: state_machines 30, entities 9, validations 6 (+3 stubs), rbac 5, cross_cutting_layers 4 (+1 stub), calculations 3 (+2 stubs), endpoints 3, consistency_model 1. Stubs cite existing §1.8 instances (deadline boundary, GPA threshold, both overlap errors, cascades, suppression).

**Lint verdict (verbatim)**:
```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
(87 endpoints, 15 entities, 19+61 instances, 1066 calls scanned, 0 violations.)

Additional audits passed: zero forbidden concurrency vocabulary; all 30 error codes referenced by validations/transitions and exercised in the designs; all system-owned enum values produced by a transition or initialization (added Student ACTIVE→ARCHIVED machine to close the one dead value); instance names unique across both design files. Replay fixes applied during authoring: reason-conditional adjustment fiscal floor (keeps OVER_DISBURSED reachable), fund re-reservation math on returns, thank-you letter idempotent auto-create, and corrected MERIT ranking arithmetic (74.50/79.50/95.00 → 83.00).

## Step 3: Copy Shared Files — 2026-08-13T14:22:00.000Z

Copied ./INSTRUCTION.md to tasks/task_1485_scholarship_search_award_matching/workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-08-13T14:40:00.000Z

PRD generation complete. The withheld difficulty/corner design files were never opened, grepped, or referenced.

## Output

**File:** `/home/ubuntu/github/CodingPRD/tasks/task_1485_scholarship_search_award_matching/workspace/PRD.md` — **391 lines**

## Section inventory

- **§1 Introduction** — 3 paragraphs (business context, audit-discipline + logical-clock design commitments, entity topology)
- **§2 Global Specifications** — 10 subsections: 2.1 RBAC (headers, 6 roles with per-role `identity:` prose), 2.2 API Response Structure (**byte-identical** to `section-2.2-response-structure.md`, verified by diff), 2.3 Pagination (limit 10/1/100, offset 0, `created_at` ascending, meta fields), 2.4 Common Resource Properties, 2.5 Money/GPA/Calendar conventions (integer cents, GPA hundredths, half-open vs closed windows), 2.6 Logical Clock & Daily Ops Run (default `2026-08-01T00:00:00Z`, three sweeps, four output counters), 2.7 OCC (3 rules with exact `expected_*_version` fields and `ERR_STALE_VERSION`/412), 2.8 Validation Order (12-priority cascade as explicit ordered prose), 2.9 Fund Accounting Invariant, 2.10 Segregation of Duties
- **§3 Business Logic** — 9 subsections (registry layer → programs/window → applications/components/reminders → eligibility scoring → committee review → awards/stacking/waitlist → disbursements → adjustments/renewals → letters/reports); parameters scattered across subsections, both cascades (A: confirm→letter→report staleness; B: stacking→auto-adjustments) fully chained
- **§4 Endpoint Definitions** — 87 rows, 4 columns; roles verified cell-by-cell against scaffold (0 mismatches)
- **§5 Error Code Catalogue** — 30 rows, 2 columns; IDs and HTTP statuses verified against scaffold (0 mismatches)

## Hard-contract audit (zero-silence / coverage)

```
Field coverage check:
- entities[].fields: 108 required, 108 present, 0 missing
- endpoints[].request_body: 77 required, 77 present, 0 missing
- endpoints[].query_params: 11 required, 11 present, 0 missing
- endpoints[].path_params: 1 required (id), 1 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority: 12 checked, 12 expressed as an ordered §2.8 cascade, 0 missing
- concurrency_rules[] OCC rejections: 3 checked, 3 expressed (write_endpoint + expected_<parent>_version + ERR_STALE_VERSION/412 each named), 0 missing
- state_machines[].transitions: 68 checked, 68 fully expressed (preconditions paired with error ids, side effects stated), 0 missing
- calculations[]: 10 checked, 10 fully expressed in precise prose (weights, caps, tie-breaks, pinned split rounding with worked example, boundary inclusivity), 0 missing
- validations[] conditions: 30 error ids, all matchable to trigger prose in §2/§3, 0 missing
- endpoints[].side_effects / applies_to: 87 checked, 87 expressed (incl. multi-endpoint scopes: ERR_AWARD_NOT_ACCEPTED on create+send, ERR_MAX_RENEWALS_REACHED on create+finalize), 0 missing
- entities[].fields[] structured content: defaults/nulls/initial values reconstructible from prose, 0 missing
- sibling-branch symmetry: 8 groups checked (RENEW/LAPSE, accept/decline/revoke/expire, MERIT/NEED/HYBRID ×2, ANNUAL/PER_TERM, STRICT/HOLISTIC, SENT-vs-CONFIRMED returns), 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 715
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional checks: all 79 enum/state values present as exact UPPERCASE strings; zero fuzzy words (approximately/about/roughly/etc.); zero operator leakage (`==`, `>=`, `+=`…) in prose; PRD ends at §5 with no audit footer.

## Step 5: Generate Unit Tests — 2026-08-13T15:20:00.000Z

Done. Complete test infrastructure generated for task_1485 (Scholarship Search & Award Matching).

## Files written (5,731 lines total)

**`test_helpers/`** (1,895 lines) — all under `/home/ubuntu/github/CodingPRD/tasks/task_1485_scholarship_search_award_matching/test_helpers/`:
- `types.py` (415) — 15 entity TypedDicts + 18 status/field enums + role enum
- `api_client.py` (456) — `ApiClient(GenericApiClient)` with 64 methods, one per PRD §4 endpoint (paths carry the `/api` prefix)
- `api_errors.py` (74) — 30 `ApiErrorId` values + HTTP status map registered with the framework
- `assertions.py` (230) — per-entity assertions, `assert_fund_availability_invariant`, `assert_instant_equal` (semantic logical-clock compare), `assert_score_equals` (2dp numeric compare), `assert_millisecond_timestamp`
- `factories.py` (186) — payload factories with auto-unique emails/names
- `constants.py` (51) — clock default, reminder offsets, deep-need bonus, score cap, 14-day offer expiry, 180-day terms, pagination bounds
- `test_users.py` (60) — `TEST_USERS` + `make_*_headers` builders (entity-backed Student/Donor builders used for all ownership-gated calls)
- `fixtures.py` (385) — tiered composites: `drive_to_selected`, `setup_finalized_cycle` (N-student committee flow), `setup_offered_award` / `setup_accepted_award` / `setup_fully_disbursed_award` / `setup_pending_renewal`, `send_and_confirm` (segregation-safe), clock/ops wrappers
- `__init__.py` (38) — barrel export

**`test_suite/`** (3,836 lines) — `conftest.py` + 15 concern-grouped files, **98 tests**, all collected cleanly by pytest, pyflakes-clean.

## Queue verdicts

- **Queue A (Difficulty): 19/19 instances emitted, exactly 2 tests each (38 tests).** No skips.
- **Queue B (Corner): 58/61 non-stub instances emitted (60 tests; two instances got a bonus second test). 3 skipped:**
  - `entities/student_create_computed_field_input_ignored` — PRD never says whether a client-supplied computed field is ignored vs rejected (two-reader failure).
  - `entities/student_create_system_fields_input_ignored` — same ignore-vs-reject ambiguity for client-supplied `id`; additionally PRD never pins the initial `version` value (only per-endpoint "+1" increments, which are tested via captured versions in the OCC tests).
  - `validations/validation_pagination_limit_out_of_range_rejected` — PRD §2.3 pins limit range [1,100] but names no error for out-of-range values on list reads (§2.8 request-shape applies to "every create and edit", not GET lists).
- **9 `excluded_because` stubs** left untranslated; all their difficulty-instance cross-references verified to resolve.

## Stage 2 self-audit verdict: PASS

- Every one of the 98 tests carries exactly one `Design:` tag resolving verbatim to a real instance name (machine-checked against both yamls).
- Full-quote verbatim citation check passes: every quoted citation in every docstring is a contiguous substring of PRD.md (whitespace-normalized).
- All 29 asserted `error_id`s are named in PRD prose (§1–§4), not just the §5 table.
- No `skip`/`skipif`/`xfail` markers; no "scaffold" references in generated code.
- One deliberate PRD adjudication: `run_daily_closes_program_expires_drafts` asserts the expired draft's reminders are **SENT** (not SUPPRESSED as the design instance claimed), because PRD §2.6's sweep order (reminder dispatch before program close) uniquely derives that outcome; the docstring quotes §2.6 to justify it.

## Step 6: Generate Implementation — 2026-08-13T15:20:00.000Z

Implementation complete. Summary:

## Files written (all under `.../workspace/implementation/`)

| File | Lines | Purpose |
|---|---|---|
| `start.sh` | 10 | Guarded pip install + `exec python3 app.py`, `$PORT`/0.0.0.0, foreground |
| `requirements.txt` | 1 | flask>=3,<4 |
| `app.py` | 65 | Flask entry, error handlers, per-request store lock |
| `db.py` | 78 | In-memory store (empty at boot, no seeding), `mutate()` with version/updated_at bump-on-change |
| `clock.py` | 64 | Logical clock, default `2026-08-01T00:00:00Z`, ISO8601 3-fraction-digit formatting |
| `errors.py` | 47 | All 30 error IDs with exact HTTP statuses |
| `response.py` | 63 | Envelope (`meta.api_request_id/api_request_timestamp`, `response_type`, `data`), limit/offset pagination with validation |
| `middleware.py` | 38 | `X-User-ID`/`X-User-Role` auth, 6 roles, 401/403 |
| `services/calc.py` | 111 | Decimal-based scoring/split math |
| `services/engine.py` | 349 | Fund/student aggregate reconciliation, stacking cascade, waitlist promotion, TYL/report staleness, reminder scheduling |
| `services/validate.py` | 94 | Typed field/enum/date validation |
| `routes/` (10 files) | ~1900 | parties, programs, applications(+components/reminders), review(cycles+scores), awards, disbursements, adjustments, renewals, stewardship(letters+reports), ops(clock/run_daily) |

## Coverage

- **Endpoints: 87/87** — programmatically diffed against the PRD §4 table, exact method+path parity, zero missing/extra.
- **State machines: 12/12**, including Award's dual dimensions (offer_status × funding_status), cyclic loops (component resubmission, score recall, DELIBERATION↔SCORING reopen, renewal appeal, disbursement reschedule retry, TYL revision), and all system-driven transitions (run_daily sweeps, UNDER_REVIEW sweep, finalize ranking, waitlist promotion, offer expiry).
- **Calculations: 10/10** — eligibility score (STRICT zero-gate vs HOLISTIC partial, exact weight sets, 2dp half-up Decimal), stacking cap (ANNUAL vs PER_TERM floor-half), over-award recovery (single pass, accepted_at DESC/created_at DESC, reducible headroom = amount − net_confirmed, auto PENDING_APPROVAL adjustments), committee ranking (weight sets, deep-need +5, cap 100, cycle_score average, 4-way tie-break), reminder cadence (past offsets skipped, equality dispatches), disbursement split (earliest-remainder: 1000000/3 → [333334, 333333, 333333], 180-day closed windows), fund availability invariant, renewal thresholds (inclusive ≥), donor report aggregation (half-open period), window gates (publish inclusive ≥, submit strict <).
- **OCC: 3/3** (`expected_program_version`/`expected_fund_version`/`expected_award_version` → 412; missing field → 400), version bumps exactly once per logical mutation including cascades.
- **Validation order** follows PRD §2.8 priorities, including PRD-faithful orderings like COMPONENT_INCOMPLETE (business, 10) before DEADLINE_PASSED (temporal, 11) and segregation-of-duties on both adjustment approval and disbursement confirm.

## Smoke test result

Fresh `bash start.sh` boot on port 14851: HTTP-ready in ~1s, store empty (`total_count: 0`), `POST /api/_clock/set_current_utc` echoes `{"now": "2026-08-01T00:00:00Z"}`, `GET /api/scholarship-programs` returns the correct array envelope with pagination meta. Beyond smoke: I ran four end-to-end suites (~115 assertions, all passing) covering the full lifecycle — student/program/application/components/submit, reminders suppress/re-arm, cycle quorum/finalize/rank, award offer/accept/decline/revoke with waitlist promotion, stacking-cap auto-adjustment with approve, schedule-split, send/confirm segregation, FULLY_DISBURSED → TYL auto-create (WAIVED for anonymous donors) → report staleness/regenerate/send/acknowledge, mark-returned clawback with funding transitions, renewals (verify boundary 250==250 passes, appeal cycle, RENEW tranche, max-renewals cap), run_daily sweeps, and RBAC/ownership negatives. Test server stopped and temp files cleaned up.

## Step 7: Run Tests and Iterate — 2026-08-13T15:50:00.000Z

All 8 rounds pass 98/98 with zero failures in the union. The sweep is clean.

## Summary

- **Iterations run:** 2 (initial sweep: 9 deterministic failures across all 8 rounds; post-fix sweep: 98/98 × 8 rounds, union empty).
- **Tests deleted:** none. One assertion was removed from `test_09_awards_and_stacking.py::test_per_term_scope_cascades_auto_adjustment` (STEP 1c partial-coverage split): `student["excess_cents"] == 500000` is not uniquely derivable — PRD §3.1 defines `excess_cents` verbatim against the annual `aid_cap_cents` ("zero when `total_accepted_cents` is at or below `aid_cap_cents`, and the difference otherwise"), while §3.6's PER_TERM "excess" is a stacking-check-local figure the PRD never writes to the student field. A §3.1-faithful reader produces 0. The test's verbatim-covered assertions (PER_TERM cap → one auto OVER_AWARD adjustment of −500000 in PENDING_APPROVAL) were kept.

- **Fixes applied to `test_helpers/`:**
  - `/home/ubuntu/github/CodingPRD/tasks/task_1485_scholarship_search_award_matching/test_helpers/fixtures.py` — `setup_finalized_cycle`: added the `student_overrides` single-student shorthand (4 call sites in 3 test files passed it; the helper only accepted the `student_specs` list). Fixed 5 tests failing with `TypeError: unexpected keyword argument`.
  - Same file — `setup_offered_award`: the composite fixture now fills `program_overrides["award_amount_cents"]` with `max(500000, amount_cents)` when the caller doesn't set the cap, so the built program satisfies PRD §3.6's "offered `amount_cents` … at most the program's `award_amount_cents`" for awards above the 500000 factory default. Fixed the HTTP 400 setup failures in `test_accept_moves_offer_and_funding_together` and `test_confirmations_advance_funding_while_offer_stays_accepted`.

- **Fixes applied to `test_suite/`:**
  - `/home/ubuntu/github/CodingPRD/tasks/task_1485_scholarship_search_award_matching/test_suite/test_15_occ_priority_and_invariants.py` — `test_offer_reserves_from_available`: its setup offered 1000000 against a default-cap (500000) program, a precondition PRD §3.6 forbids; added `award_amount_cents=1000000` to the `create_open_program` call, matching the sibling test's pattern.
  - `/home/ubuntu/github/CodingPRD/tasks/task_1485_scholarship_search_award_matching/test_suite/test_09_awards_and_stacking.py` — removed the non-derivable `excess_cents` assertion noted above (with a comment recording the §3.1 rationale).

- **Fixes applied to `implementation/`:**
  - `/home/ubuntu/github/CodingPRD/tasks/task_1485_scholarship_search_award_matching/workspace/implementation/routes/disbursements.py` — `confirm_disbursement`: a re-confirm after a return+reschedule retry now clears the internal `_returned_from_confirmed` marker. Previously the sticky marker kept `net_confirmed` at 0 forever, so the award was stuck at `ENCUMBERED` instead of re-reaching `FULLY_DISBURSED` after the §3.7 retry cycle ("the row returns to `SCHEDULED` with … `sent_at`, `confirmed_at`, and `returned_at` cleared" — the retry supersedes the earlier return). Fixed `test_return_unwinds_money_and_reconfirm_restores`.

No implementation checks were weakened, no endpoints/fields added beyond PRD, and no tests were skipped or downgraded.

## Step 8: Finalize PRD — 2026-08-13T16:05:00.000Z

Done. `PRD_FINALIZED.md` written at `/home/ubuntu/github/CodingPRD/tasks/task_1485_scholarship_search_award_matching/workspace/PRD_FINALIZED.md`.

## Summary

**Line counts:** PRD.md 391 lines → PRD_FINALIZED.md 391 lines (0.0% line delta; both edits are inline sentence insertions on existing lines, adding ~110 words total).

**Changes (2 edits, both insertions — no verbatim text altered):**

- **§3.6** — insert — appended to the stacking-cap paragraph: the stacking excess is local to the check, drives only the over-award recovery pass, and is never written to the student record; the stored `excess_cents` is always the §3.1 figure computed against the annual `aid_cap_cents` regardless of the triggering program's `stacking_scope` — `implementation/services/engine.py:88-96` (`recompute_student`, sole post-registration writer, always annual) and `engine.py:119-121` (scope-based excess kept as a local).
- **§3.7** — insert — appended to the reschedule sentence: the retry supersedes the earlier return in fund arithmetic — a row returned from `CONFIRMED` keeps counting in gross `disbursed_cents` while `RETURNED` or awaiting retry, and on re-confirm it counts in full toward net confirmed again, leaves `returned_cents`, and the award can re-reach `FULLY_DISBURSED` — `implementation/routes/disbursements.py:150-151` (confirm sets `_ever_confirmed=True`, clears `_returned_from_confirmed`), `engine.py:55-63` (`net_confirmed`), `engine.py:151-171` (`recompute_funding_status`).

**Step-7 items judged non-PRD (no edit):** `setup_finalized_cycle` `student_overrides` shorthand (pure test-helper API bug); `setup_offered_award` cap fill and test_15 `award_amount_cents=1000000` (fixture/test precondition fixes — §3.6's "offered `amount_cents` … at most the program's `award_amount_cents`" was already pinned verbatim and is enforced at `implementation/routes/awards.py:48-49`).

**Per-edit pre-edit search log:**

1. **§3.6 excess edit.** (a) Subject: stored student `excess_cents` vs stacking-check excess. (b) Enumerated paths: `routes/parties.py:79` (init 0), `parties.py:125-131` (COA/EFC trigger), `parties.py:151-169` (aid-summary recomputes then serializes), `services/engine.py:88-96` (`recompute_student`), `engine.py:103-144` (`stacking_recompute`, local excess never persisted), all five trigger callsites (`routes/awards.py:128,145`, `routes/adjustments.py:104`, `routes/renewals.py:159`, `routes/parties.py:131`), plus disbursement confirm/return cascades (`engine.py:231-261`); test-suite grep confirmed all surviving `excess_cents` assertions (0/0/300000/0) are annual-cap figures. (c) Wording chosen as "remains the §3.1 figure — always computed against the annual `aid_cap_cents`, regardless of the triggering program's stacking scope" to also cover the no-trigger-program path (student update, `engine.py:112-118` most-restrictive scope selection) without making any claim about that selection rule itself (out of Step-7 scope).
2. **§3.7 retry edit.** (a) Subject: what a re-confirmed-after-return row contributes to net confirmed, `disbursed_cents`, `returned_cents`, and `funding_status`. (b) Enumerated paths: `routes/disbursements.py:94-95,150-151,166-171,188-192,199-202` (create/confirm/mark-returned/reschedule/cancel flag handling), `routes/awards.py:205-221` (schedule-split initializes identical flags — edit wording covers any disbursement row, not just manual), `services/engine.py:55-63,66-85,151-171` (net_confirmed/recompute_fund/funding thresholds), and all `net_confirmed` consumers (`awards.py:172` revoke, `adjustments.py:94` approval floor, `engine.py:132` stacking headroom, `parties.py:166` aid-summary). (c) Wording scoped to "a row returned from `CONFIRMED`" so it stays silent — and consistent — on: returns from `SENT` (no money moved, flags untouched), mid-retry cancellation (flags persist, net contribution 0; PRD's "excluded from funding arithmetic" untouched), donor-report staleness and letter dedup on re-reaching `FULLY_DISBURSED` (pre-existing §3.7/§3.9 text left verbatim; impl's early-return in `engine.py:214-215` not claimed either way), and gross-per-row (not per-confirm-event) accumulation.

## Step 9: Complete PRD — 2026-08-13T16:25:00.000Z

## Summary

Produced `/home/ubuntu/github/CodingPRD/tasks/task_1485_scholarship_search_award_matching/workspace/PRD_COMPLETED.md` as a minimal patch over `PRD_FINALIZED.md`.

**Size:** PRD_FINALIZED.md 391 lines / 70,802 chars → PRD_COMPLETED.md 391 lines / 73,908 chars (char-delta **+3,106**; line count unchanged — all changes are inline, no new sections or paragraphs).

**Counts:** 22 ambiguity-pins, 8 mismatch-revisions (30 touched lines total).

### Changes

- **§2.1** — insert — ambiguity — transitive student ownership: components, disbursements, renewal evaluations are owned through the parent application's/award's `student_id` — implementation/routes/applications.py:39-43, disbursements.py:27-31, renewals.py:26-30
- **§2.1** — insert — ambiguity — donor ownership extends to own donor record and to thank-you letters of awards whose program names the donor — implementation/routes/parties.py:200-201, stewardship.py:44-46
- **§2.3** — insert — ambiguity — non-integer `limit`/`offset`, `limit` outside 1–100, or negative `offset` rejected with `ERR_VALIDATION` — implementation/response.py:33-54
- **§2.3** — insert — ambiguity — same-instant `created_at` ties break by creation sequence, in the ordering's direction, for lists, ranking, and reminder dispatch — implementation/response.py:61-63, routes/review.py:179-180, routes/ops.py:42
- **§2.4** — insert — ambiguity — a write changing nothing does not increment `version` or refresh `updated_at` — implementation/db.py:52-62
- **§2.6** — insert — ambiguity — clock-set response echoes the supplied string verbatim as `now` — implementation/clock.py:38-46, routes/ops.py:26
- **§2.6** — revise — mismatch — ops-run app expiry hits every `DRAFT` application of any `CLOSED` program past its close, not only programs closed in that run — implementation/routes/ops.py:53-61
- **§2.8** — revise — mismatch — validation order: existence (step 3) precedes ownership (step 4); create requests validate body-id presence/existence before ownership — systematic across handlers (e.g. parties.py:86-89, awards.py:134-137, applications.py:57-62)
- **§3.1** — insert — ambiguity — duplicate student `email` refused with `ERR_VALIDATION` — implementation/routes/parties.py:58-60
- **§3.1** — insert — ambiguity — aid-summary response shape: student record fields plus `awards` array of `{award_id, application_id, amount_cents, offer_status, funding_status, net_confirmed_cents}` — implementation/routes/parties.py:151-169
- **§3.1** — insert — ambiguity — commitments carry a positive integer `amount_cents` — implementation/routes/parties.py:251
- **§3.2** — insert — ambiguity — `award_amount_cents` and `max_recipients` are positive integers — implementation/routes/programs.py:56-57
- **§3.3** — revise — mismatch — creation has three gates, not two: student `ACTIVE`, program `OPEN` (`ERR_PROGRAM_NOT_OPEN`), no duplicate — implementation/routes/applications.py:66-74
- **§3.3** — insert — ambiguity — adding a component to a non-`DRAFT` application fails with `ERR_INVALID_STATE` — implementation/routes/applications.py:192-193
- **§3.3** — insert — ambiguity — a reminder offset whose send time equals now is still scheduled; only strictly-past offsets are skipped — implementation/services/engine.py:297-309
- **§3.5** — insert — ambiguity — score-draft gates: cycle `SCORING` (`ERR_INVALID_STATE`), application belongs to cycle's program (`ERR_VALIDATION`), application `UNDER_REVIEW` (`ERR_INVALID_STATE`) — implementation/routes/review.py:220-225
- **§3.6** — insert — ambiguity — over-cap/non-positive offer amount or mismatched `student_id` fails with `ERR_VALIDATION` — implementation/routes/awards.py:45-51
- **§3.6** — insert — ambiguity — stacking cap basis for non-acceptance triggers: edit/adjustment/renewal use the affected award's own program scope; COA/EFC change uses the most restrictive scope among accepted awards (`PER_TERM` if any) — implementation/services/engine.py:103-118
- **§3.6** — insert — ambiguity — auto-generated adjustments carry `created_by_user_id` null, so segregation never blocks their approval — implementation/services/engine.py:135-143
- **§3.7** — insert — ambiguity — split-plan rows carry the student's own `institution_name` and the action responds with the array of generated rows; refusal trigger is any non-`CANCELLED` disbursement — implementation/routes/awards.py:195-222
- **§3.7** — revise — mismatch — return-driven `funding_status` recompute (incl. `OVER_DISBURSED`→`FULLY_DISBURSED`) applies only while the offer remains `ACCEPTED` — implementation/services/engine.py:151-171
- **§3.8** — revise — mismatch — the adjustment-apply `OVER_DISBURSED` flip (both mentions) applies only to `ACCEPTED` awards — implementation/routes/adjustments.py:100-101
- **§3.8** — insert — ambiguity — renewal-create gate failures (non-renewable program, award not `FULLY_DISBURSED`) are `ERR_INVALID_STATE` — implementation/routes/renewals.py:49-52
- **§3.8** — insert — ambiguity — a null renewal threshold imposes no requirement on its leg — implementation/routes/renewals.py:113-120
- **§3.8** — insert — ambiguity — renewal does not recompute `funding_status`; it remains `FULLY_DISBURSED` despite the enlarged amount — implementation/routes/renewals.py:155-159
- **§3.9** — insert — ambiguity — waiving a letter, like delivery, reverts covered `GENERATED` reports to `DRAFT` — implementation/routes/stewardship.py:146
- **§3.9** — insert — ambiguity — the read-time `thank_you_complete` refresh applies only to reports that have left `DRAFT` — implementation/routes/stewardship.py:201-204
- **§3.9** — revise — mismatch — report staleness triggers on a covered letter being delivered or waived (terminal states are entered, never left) — implementation/services/engine.py:187-199
- **§4** — revise — mismatch — the split-plan action returns `200 OK` (with the generated array), not the blanket 201 for creates — implementation/routes/awards.py:222

No behavior was invented; every pin cites the implementing line. Everything else in the PRD (scoring formulas, weights, fund invariant, OCC fields, cascades, error catalogue, endpoint/role matrix) already matched the implementation uniquely and was left untouched.
