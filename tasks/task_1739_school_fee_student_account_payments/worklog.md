# Worklog — task_1739_school_fee_student_account_payments

## Step 1: Create Task Directory — 2026-08-14T12:15:00.000Z

Task directory `tasks/task_1739_school_fee_student_account_payments/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline launcher. Step 1 treated as DONE per instructions; no index scan performed, no other task_* directory touched.

## Step 2: Generate Scaffold — 2026-08-14T13:25:00.000Z

All three artifacts are written and lint-clean:

- `/home/ubuntu/github/CodingPRD/tasks/task_1739_school_fee_student_account_payments/SCAFFOLD.yaml`
- `/home/ubuntu/github/CodingPRD/tasks/task_1739_school_fee_student_account_payments/SCAFFOLD_DIFFICULTY_DESIGN.yaml`
- `/home/ubuntu/github/CodingPRD/tasks/task_1739_school_fee_student_account_payments/SCAFFOLD_CORNER_DESIGN.yaml`

**Lint verdict (verbatim):** `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (816 calls scanned across both design files.)

**Counts:**
- Entities: 20
- State machines: 13 (52 transitions), including cyclic machines on PaymentPlanInstallment (PAST_DUE→PAID recovery) and CollectionsCase (OPEN→PAYMENT_PROMISED→OPEN broken-promise loop)
- Calculations: 10 (waiver_stacking, refund_proration, allocation_waterfall, installment_schedule, collections_aging, posture_recompute, department_distribution, family_balance, write_off_reconciliation, purchase_charge)
- Validation rules: 23 (ordered priority 1–23)
- Endpoints: 109
- Error codes: 34
- Roles: 3 (Bookkeeper, FamilyMember, Superintendent — segregation_of_duties model)
- Concurrency rules: 3 (all OCC on parent `version`, 412 ERR_STALE_VERSION)
- §1.8 instances: 18 (9 rules × 2, every differentiation clause honored: waiver vs refund domains; formula modes (a) caps/priority waterfall vs (b) nested-rounding remainder; different cascade triggers, error-category pairs, boundary metrics/endpoints, entity pairs, interval semantics, conserved quantities)
- §1.9 instances: 68 total (57 active + 11 `excluded_because` stubs citing §1.8 instances), spanning all nine claim-extraction-guide sections

**Notable design decisions:**
1. **Dual ledger model**: fee obligations (assessed/waived/paid/balance) are strictly disjoint from purchase money (purchases charge atomically, never enter balance math) — keeps the distribution invariant clean while reconciliation still verifies both via `expected_d` including COMPLETED/REFUNDED purchases.
2. **Refund collapse semantics**: withdrawal/cancellation refunds reduce `allocated_cents` and transition the assessment to REFUNDED with the retained portion counted in `assessed_cents` — this makes the compensating invariant `distributed == gross allocations + purchases − refunds − write-offs` hold exactly.
3. **Pinned rounding orders everywhere**: waiver stacking is floor-then-cap per program; waterfall Stage-1 proportional split is half_up per row with the over/under cent assigned to the earliest-created covered assessment; installment remainder goes to the LAST installment. The §1.8 rounding instance pins 1666/3334 as the exact expected split.
4. **Two interval semantics for Rule 8**: SchoolYear ranges use closed-interval collision (shared endpoint date collides); enrollment schedule conflicts use half-open [start, end) (adjacency allowed) — on different resources.
5. **Logical clock with mandatory default** `2026-08-01T00:00:00Z` via `POST /_clock/set_current_utc`; all aging, proration, and lazy offering transitions read it — no wall-clock dependence.
6. **Segregation of duties at two layers**: waiver self-approval ban (X-User-ID vs submitted_by_user_id) and write-off SoD vs the most recent payment recorder, plus a Superintendent co-approval gate above `writeoff_max_cents`.
7. **Lint-driven path layout**: the linter's FK check requires literal `{id}` parent segments and prefix-rooted collections, so `api_prefix` is empty and 35 flat alias/reverse-reachability GETs were added — every one of the 36 FKs is reverse-reachable.

## Step 3: Copy Shared Files — 2026-08-14T13:31:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1739_school_fee_student_account_payments/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-14T13:58:00.000Z

PRD generation complete. `/home/ubuntu/github/CodingPRD/tasks/task_1739_school_fee_student_account_payments/workspace/PRD.md` is fully written. The two withheld design files were never opened or read.

## Summary

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1739_school_fee_student_account_payments/workspace/PRD.md` — **439 lines**

**Section list:**
- 1. Introduction (2 paragraphs)
- 2. Global Specifications: 2.1 Roles & headers, 2.2 API Response Structure (byte-identical to the canonical fixed block — verified), 2.3 Pagination, 2.4 Logical Clock (default `2026-08-01T00:00:00Z`, lazy transitions), 2.5 Common Resource Properties & Version (incl. PaymentAllocation/LedgerEntry carrying only `id`/`created_at`), 2.6 Integer Cents & Pinned Rounding Order, 2.7 Half-Open vs Closed Interval Semantics, 2.8 Hierarchy/Nested Retrieval/Recompute, 2.9 OCC, 2.10 The Validation Ladder (all 23 priorities in order), 2.11 Department Revenue Ledger
- 3. Business Logic: 3.1 Year config/catalogs, 3.2 Students/accounts/posture/family balance, 3.3 Offerings & enrollment, 3.4 Waivers & stacking waterfall, 3.5 Payments/purchases/allocation waterfall, 3.6 Payment plans & installments, 3.7 Withdrawals/cancellations/refunds, 3.8 Collections/write-offs/reconciliation
- 4. Endpoint Definitions — 109-row table (verified 1:1 against scaffold, roles parity verified)
- 5. Error Code Catalogue — all 34 errors with correct HTTP statuses (verified per-row)

**Coverage self-audit (all three hard contracts PASS):**

*Contract 1 — Field-name coverage:* 87 entity fields + 53 request-body identifiers + 13 path params + 12 query params = 106 required identifiers, all present as exact tokens (word-boundary matched). PASS after fixes for `payment_id` and normalization pass.

*Contract 2 — Rule coverage:*
- validations with priority: 23/23 expressed in the ordered ladder plus per-endpoint orderings (enrollment uniqueness→capacity→window→conflict; waiver SOD before eligibility; write-off aging→governance→SOD; OCC last)
- concurrency rules: 3/3 with write endpoint, occ field, `ERR_STALE_VERSION`/412 named
- state transitions: 52/52 expressed with from→to pairs co-located and all 17 precondition error ids present
- calculations: 10/10 in prose — floor-then-cap waiver stacking with per-student cap consumed earliest-`created_at`-first, proration tiers with inclusive boundaries, waterfall stage 1 half-up proportional split with residual cent to earliest-created covered assessment, stage-2 ordering (created_at asc, amount desc tie-break), REJECT pre-check atomicity, installment floor division with remainder to LAST installment, aging buckets k/2k/3k with ≥-lower/<-upper edges, posture strict-`>` threshold, write-off proration remainder to earliest ledger entry, reconciliation invariant, purchase/fee ledger disjointness
- 97/97 semantic spot-checks passed; endpoint side effects (ops-run output fields, summary fields, lazy read transitions, version increments) all rendered

*Contract 3 — §3 path purity:* 334 backtick tokens scanned in §3, zero paths/methods. PASS.

Sibling-branch symmetry verified (SCHEDULED vs IN_SESSION cancellation, settle outcomes, write-off from OPEN and PAYMENT_PROMISED, resolve paths).

## Step 5: Generate Unit Tests — 2026-08-14T14:25:00.000Z

## Generation complete

**Files written under `test_helpers/`** (9 files):
- `types.py` — 20 entity TypedDicts + 18 status/role enums; `PaymentAllocation` and `LedgerEntry` correctly omit `updated_at`/`version` per PRD §2.5 (immutable ledger rows).
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint (66 methods incl. flat aliases used).
- `api_errors.py` — `ApiErrorId` enum + HTTP map (all 34 catalog entries) registered via `set_error_http_status_map`.
- `assertions.py` — per-entity `assert_*` validators + `assert_account_invariants` (balance = assessed − waived − paid).
- `factories.py` — one payload factory per creatable entity, input fields only.
- `constants.py` — clock default `2026-08-01T00:00:00Z`, BP denominator, year policy knobs.
- `test_users.py` — `TEST_USERS` for the 3 opaque roles + per-user builders (`make_bookkeeper_headers` etc.) used where SoD compares recorded operator ids (waiver review, write-off SoD).
- `fixtures.py` — composite builders: `setup_open_year`, `setup_year_with_fee`, `add_student_with_account`, `setup_account_with_assessment`, `setup_account_enrolled`, `pay_and_settle`, `setup_account_with_plan`, `age_account_to_collections`, `setup_account_with_collections_case`, `advance_case_to_bucket3`, `setup_written_off_account`, `submit_and_approve_application`, `setup_approved_waiver_account`, `set_clock`, `current_account_version`.
- `__init__.py` — barrel export.

**Files written under `test_suite/`** (12 files): `conftest.py` + 11 test modules grouped by concern (year config, students/accounts, offerings/enrollments, payments/waterfall, waivers, refunds, payment plans, collections/write-offs, ledger/reconciliation, RBAC/OCC/catalog, reads/summary).

**Coverage:**
- Queue A (Difficulty): **18/18 instances, each with ≥2 tests** (36 difficulty-tagged tests).
- Queue B (Corner): **57/57 non-stub instances, each with ≥1 test**; the 11 `excluded_because:` stubs were verified to resolve to real difficulty instances and were not translated.
- Total: **102 test functions**, zero skipped instances (every instance passed the PRD-first two-condition filter — the PRD covers every rule including the two priority-ordering instances, via §2.10's explicit ladder ordering).

**Verification performed:**
- All 146 PRD citations across the docstrings pass a whitespace-insensitive verbatim check against `workspace/PRD.md` (C1/C2/C3). This required two repair rounds: stripping sentence-final periods where the PRD sentence continues with `—`/`;`, removing bold-header prefixes (`**From-state.**` etc.) from quotes, and splitting `...`-bridged spans into separate verbatim quotes.
- Every test ends with exactly one `Design: Difficulty/<rule_id>/<name>` or `Design: Corner/<section>/<name>` line resolving to a real instance; no invalid, missing, or dual tags.
- No `pytest.mark.skip`/`skipif`/`xfail` anywhere.
- All modules compile and import cleanly under the runner's PYTHONPATH.

**Skipped instances:** none — no PRD-silence gaps were hit; every instance in both queues has verbatim PRD coverage with uniquely-derivable outcomes.

## Step 6: Generate Implementation — 2026-08-14T14:45:00.000Z

Implementation complete and verified. All work is in `/home/ubuntu/github/CodingPRD/tasks/task_1739_school_fee_student_account_payments/workspace/implementation/`.

## Files written

- `start.sh` — foreground launcher, `exec python3 app.py`, guarded dependency install (`import flask` check) so per-test reboots skip pip; binds `0.0.0.0:$PORT` (default 10000); measured fresh boot ~0.7s
- `requirements.txt` — flask only
- `app.py` — Flask app, blueprint registration, envelope-compliant error handlers (ApiError, 404/405/400, catch-all)
- `core.py` — logical clock (default `2026-08-01T00:00:00Z`, `POST /_clock/set_current_utc` with `to_iso8601`→`now_iso8601`), in-memory `Store` (20 dicts, **empty at boot, no seeding**), envelope/pagination helpers (`meta`/`response_type`/`data`, `limit`/`offset`/`total_count`/`has_more`), auth (X-User-ID/X-User-Role), and the domain engine: account recompute + posture priority, family balance, live aging buckets, waiver stacking, allocation waterfall, refund proration
- `serializers.py` — per-entity field whitelists in scaffold order (internal `_`-prefixed fields never leak); ledger/allocation rows carry only `id`+`created_at` (no `updated_at`/`version`)
- `routes_years.py` (clock, years, open/close, ops-run sweep, departments, fee items, purchase items, offerings), `routes_students.py` (students, withdraw cascade, graduate, accounts, summary), `routes_money.py` (enrollments, assessments, purchases, payments, plans), `routes_waivers_refunds.py`, `routes_collections.py` (ledger, reconciliation, cases, promise/approve-writeoff/write-off), `routes_alias.py` (13 flat aliases + 22 reverse lookups)

## Endpoint count

All **109 endpoints** from the scaffold table implemented (core + flat aliases + FK reverse lookups). Verified with ~140 ad-hoc smoke assertions covering: envelope shape, pagination clamping, ladder ordering (412 OCC last, SoD before eligibility, 402 REJECT pre-check atomicity), half-open offering windows vs closed year ranges (shared endpoint collides), floor-then-cap waiver stacking with chronological cap consumption, stage-1 half-up proportional split with residual cent to earliest-created covered assessment, installment remainder-to-last, refund proration tiers (inclusive edges, SCHEDULED-cancel = full), plan default cascade, broken-promise reversion, BUCKET_3 write-off gates (aging→governance→SoD), reconciliation invariant (no drift), and WRITTEN_OFF settle refusal.

## Ambiguities resolved (interpretation chosen)

1. **`ERR_YEAR_NOT_OPEN` scope** — applied to enrollment create/withdraw, assessment create/void, purchase create, payment create/settle/void, plan create/cancel (the "enrollment/assessment/purchase/payment/plan write" enumeration); NOT to waiver, refund, or collections writes, per PRD §2.10 rung-5 wording.
2. **Purchase refunds vs `paid_cents`** — PRD §2.11 ("purchase refunds never touch account balance math") wins over the looser §3.2 formula; `paid_cents` subtracts only fee-sourced and OVERPAYMENT_RETURN refunds.
3. **WRITE_OFF_DEBIT sign** — stored negative so `distributed_cents` (sum of all signed rows) satisfies the reconciliation invariant "…minus written-off cents".
4. **Write-off proration weights** — prorated by each department's share of the account's outstanding assessment obligations (statuses ASSESSED/PARTIALLY_PAID/PAYMENT_PLAN/DELINQUENT); leftover cent to the department whose ledger entry for the account has earliest `created_at` (fallback: earliest-created prorated department when no entries exist).
5. **Aging bucket** — computed live from `(clock − opened_at)` whole-day floor on every read and gate evaluation (it's `source: computed`); sweep side-effects (delinquency, defaults, case opens, promise reversion) remain sweep-only.
6. **`WAIVED` only from `ASSESSED`** — per the state machine; a PARTIALLY_PAID assessment whose waivers reach `allocated + waived == assessed` stays PARTIALLY_PAID with `outstanding_cents == 0`. Revoke returns WAIVED→ASSESSED (or PARTIALLY_PAID if allocated > 0).
7. **Plan cancel/default `payment_plan_id`** — cleared only on COMPLETED (explicit in PRD) and on refund to REFUNDED; kept on CANCELLED/DEFAULTED so the plan's covered-assessments reverse lookup stays meaningful. Cancel returns covered assessments to ASSESSED (or PARTIALLY_PAID when partial allocations exist — PRD's flat "ASSESSED" would corrupt those rows' semantics).
8. **Cancellation refund rows** — spawned per dropped enrollment even for non-refundable fee items (computing to 0 per §3.7), while single-enrollment withdrawal spawns a row only when refundable (explicit asymmetry in §3.3).
9. **Version bumps** — every mutation (including recomputes and lazy transitions) refreshes `updated_at`/`version` on the mutated entity; sibling accounts' `family_balance_cents` is computed live at read so sibling version numbers don't jump (prevents spurious OCC failures).
10. **Duplicate external_ref / department code** — rejected with `ERR_INVALID_REQUEST` (400); no dedicated catalog error exists.

## Step 7: Run Tests and Iterate — 2026-08-14T15:05:00.000Z

All 8 rounds pass 102/102. The verification sweep is clean. (The two monitor tasks exiting 144 is just SIGTERM cleanup after the main sweep completed — results were verified directly from the JSON files.)

## Summary

**Iterations run:** 2 sweeps of 8 parallel rounds each (baseline + verification). Final state: **8/8 rounds at 102/102 passed**.

**Baseline failures (deterministic, all 8 rounds, union = 4 tests):**
- `test_04::test_assessment_void_success_then_activity_blocked`
- `test_04::test_waterfall_stage2_oldest_first`
- `test_05::test_waiver_revoke_restores_outstanding_for_payment`
- `test_08::test_writeoff_sod_rejected_then_other_user_succeeds`

**Tests deleted:** none. Every failing test traced to a verbatim PRD rule; all failures were setup bugs or one implementation deviation.

**Fixes applied to `test_suite/`:**
1. `/home/ubuntu/github/CodingPRD/tasks/task_1739_school_fee_student_account_payments/test_suite/test_04_payments_waterfall.py` — both waterfall tests created two ad-hoc assessments under the frozen default logical clock, producing identical `created_at`; PRD §3.5's stage-2 tie-break (`assessed_amount_cents` descending) then fired instead of the primary created_at ordering the tests assert. Inserted `set_clock("2026-08-02T00:00:00Z")` between the creates (and added `set_clock` to imports) so the primary key decides — strictly more faithful to the cited PRD sentence.
2. `/home/ubuntu/github/CodingPRD/tasks/task_1739_school_fee_student_account_payments/test_suite/test_05_waivers.py` — `test_waiver_revoke_restores_outstanding_for_payment` revoked the waiver only after the assessment was fully PAID; PRD §3.4's stacking visits only `ASSESSED`/`PARTIALLY_PAID` (plus `WAIVED` rollback) and declares no `PAID`→`PARTIALLY_PAID` transition, so the asserted rollback was not uniquely derivable (STEP 1b/1c). Changed the pre-revoke payment to a partial 2000 (assessment `PARTIALLY_PAID`), kept the covered assertions (`waived_cents == 0`, `balance_cents == 6000`), and added a final 6000 settle proving the restored outstanding is payable — preserving the design instance's roundtrip-conserves-balance intent on PRD-solid ground.
3. `/home/ubuntu/github/CodingPRD/tasks/task_1739_school_fee_student_account_payments/test_suite/test_08_collections_writeoffs.py` — `test_writeoff_sod_rejected_then_other_user_succeeds` crashed with `KeyError: 'case'`: its hand-rolled setup called `advance_case_to_bucket3(env)` which reads `env["case"]`, never stored. Added `env["case"] = cases[0]`.

**Fixes applied to `test_helpers/`:** none needed.

**Fixes applied to `implementation/`:**
4. `/home/ubuntu/github/CodingPRD/tasks/task_1739_school_fee_student_account_payments/workspace/implementation/routes_money.py` — `void_assessment` checked `status != ASSESSED` first (ERR_INVALID_STATE), making the PRD-named `ERR_ASSESSMENT_HAS_ACTIVITY` unreachable (an `ASSESSED` row is untouched by construction). Replaced with PRD §3.5's compound precondition: not (`ASSESSED` and untouched) → `ERR_ASSESSMENT_HAS_ACTIVITY` (409).

No assertions weakened, no implementation checks stripped, no data seeded.

## Step 8: Finalize PRD — 2026-08-14T15:20:00.000Z

Step 8 complete. `/home/ubuntu/github/CodingPRD/tasks/task_1739_school_fee_student_account_payments/workspace/PRD_FINALIZED.md` is produced.

## Summary

**Line counts / delta:** PRD.md 439 lines → PRD_FINALIZED.md 439 lines, +0 lines (0.0%). All edits are inline within existing paragraph lines; no sections added or removed. Exactly 3 lines changed.

**Changes (one bullet per edit):**

- §2.10 (rung 6, line 145) — revise — carved out the single exception to the from-state rung: "Applies to all state-transition endpoints with one exception: the assessment-void endpoint, whose single compound precondition (§3.5) occupies this rung's position and fails with `ERR_ASSESSMENT_HAS_ACTIVITY` (HTTP 409) in place of `ERR_INVALID_STATE`." — `implementation/routes_money.py:237-241` (void_assessment; the only `ERR_ASSESSMENT_HAS_ACTIVITY` site in the codebase).
- §3.4 (final-stacking paragraph, line 226) — revise + insert — changed "each assessment's waived_amount_cents" to "each **visited** assessment's …" and appended: assessments in `PAID`, `PAYMENT_PLAN`, `DELINQUENT`, or `REFUNDED` status are never recomputed by stacking; their recorded waived_amount_cents stands (still counting toward waived_cents and each program's consumed per-student allowance), no waiver-driven transition fires, and "revocation in particular never returns a `PAID` assessment to `PARTIALLY_PAID`." — `implementation/core.py:484-502` (run_stacking visit set excludes these statuses; skipped rows still consume cap), `core.py:527-535` (only ASSESSED→WAIVED and WAIVED-rollback transitions exist; no PAID→PARTIALLY_PAID path), `core.py:354-362` (waived_cents sums all non-VOID rows).
- §3.5 (void-assessment sentence, line 232) — revise — kept the original sentence's precondition verbatim, then pinned that it is "a single compound check, not a from-state check followed by a separate activity check": a void attempt in any other status — `PARTIALLY_PAID`, `PAID`, `PAYMENT_PLAN`, `DELINQUENT`, `WAIVED`, `REFUNDED`, or already `VOID` — fails with the same `ERR_ASSESSMENT_HAS_ACTIVITY` (409), and the endpoint never raises `ERR_INVALID_STATE`. — `implementation/routes_money.py:237-241` (`if a["status"] != "ASSESSED" or a["allocated_cents"] != 0 or a["refunded_cents"] != 0: raise ApiError("ERR_ASSESSMENT_HAS_ACTIVITY", 409, …)`).

**Step-7 items requiring no edit:** item 1 (test_04 `set_clock` between creates — frozen-clock fixture bug; §2.4's default clock and §3.5's created_at-then-amount-desc tie-break already pin the behavior) and item 3 (test_08 missing `env["case"]` — pure fixture KeyError).

**Per-edit pre-edit search log:**

- *§2.10 rung-6 edit* — (a) subject: scope of the from-state validation rung. (b) enumerated all 23 `err_invalid_state` sites across `routes_years.py` (open/close year, retire item, complete/cancel offering), `routes_students.py` (withdraw/graduate), `routes_money.py` (withdraw enrollment, retired-item guards, settle/void payment, cancel plan), `routes_waivers_refunds.py` (suspend program, approve/deny/revoke application, execute/deny refund), `routes_collections.py` (promise, approve-writeoff, write-off) — every one raises `ERR_INVALID_STATE` on from-state failure; `void_assessment` is the sole exception, and impl ordering confirms the compound check sits at rung-6's position (after `require_year_open`, rung 5). (c) wording scoped to exactly "the assessment-void endpoint" so no other enumerated endpoint's rung-6 behavior is narrowed.
- *§3.4 stacking edit* — (a) subject: which assessments stacking recomputes on approval/revocation and the fate of non-visited rows. (b) read `core.py` run_stacking (474-536) fully, all four callers (`routes_money.py:110`, `:198` provisional; `routes_waivers_refunds.py:176`, `:209` final), and `recompute_account` (346-402); grep confirmed run_stacking is the only post-creation mutator of `waived_amount_cents`. (c) adjustments: (i) narrowed the delta sentence to "each visited assessment's"; (ii) the appended sentence lists exactly `PAID`/`PAYMENT_PLAN`/`DELINQUENT`/`REFUNDED` and deliberately omits `VOID` — impl drops VOID rows before cap accounting (core.py:485) and §3.2 says VOID contributes nothing, so including VOID in "still counting toward waived_cents and cap" would have created a new mismatch.
- *§3.5 void edit* — (a) subject: void endpoint's precondition and error code. (b) read `void_assessment` (routes_money.py:224-245) in full; grep confirmed `ERR_ASSESSMENT_HAS_ACTIVITY` exists nowhere else; enumerated the only other VOID-writer (write-off cascade, `routes_collections.py:234-239` — a different endpoint, untouched by wording scoped to the void endpoint); verified VOID aggregate exclusion (core.py:355-356) and the full assessment status universe (8 statuses), confirming the edit's seven-status enumeration is exhaustive and each maps to the compound check's first disjunct — including the already-VOID double-void case and a WAIVED row with zero activity. (c) wording preserves the original precondition sentence verbatim and appends the pin as a separate sentence, so the success path description is unchanged.

## Step 9: Complete PRD — 2026-08-14T15:45:00.000Z

All edits complete and verified. Final report:

## Summary

**Produced:** `/home/ubuntu/github/CodingPRD/tasks/task_1739_school_fee_student_account_payments/workspace/PRD_COMPLETED.md`

**Size:** PRD_FINALIZED.md 439 lines / 73,086 chars → PRD_COMPLETED.md 439 lines / 77,821 chars (char-delta **+4,735**; all edits in-paragraph, zero new sections, zero line-count change; 32 paragraphs touched).

**Counts:** 22 ambiguity-pins, 16 mismatch-revisions (38 changes total across 32 lines). All ten Step-6 resolutions are now pinned.

## Change log (abbreviated — 38 bullets)

§2.1 unrecognized role → 400 not 403; §2.3 pagination clamp/defaults, created_at tie-break by insertion order, has_more definition; §2.4 offering lazy transition also on enrollment/complete/cancel; §2.10 rung-5 year-open gate scope revised (waiver/refund/collections/withdraw/graduate/config writes ungated), rung-14 grade-band only with separate ERR_WAIVER_PROGRAM_SUSPENDED ordering, transport-level rejections (undefined path 404, unparseable body 400); §2.11 source_payment_id null on write-offs and purchase credits, WRITE_OFF_DEBIT negative, distributed_cents signed sum of all rows; §3.1 config writes any-status, duplicate dept code → 400, retired-item assessment → ERR_INVALID_STATE; §3.2 duplicate external_ref → 400, graduation hold spans all years, no (student,year) uniqueness, paid_cents purchase-refund exclusion, lazy recompute version policy + live family balance, open_case_count definition; §3.3 cancellation stamps withdrawn_at + account bumps; §3.4 stacking visited set includes WAIVED, WAIVED transition only from untouched ASSESSED; §3.5 earliest-created ACTIVE plan for stage 1, zero-share writes no allocation row, stage-2 final tiebreak insertion order, DELINQUENT→PARTIALLY_PAID partial allocation, PAYMENT_PLAN retention; §3.6 plan default moves only PAYMENT_PLAN-status covered assessments, cancel restores PARTIALLY_PAID-or-ASSESSED, payment_plan_id retention rules; §3.7 cancellation refund rows unconditional (0 for non-refundable), student-withdraw plan cancel waives SCHEDULED/DUE/PAST_DUE, refund sets REFUNDED from any status + clears plan id; §3.8 ops run any-status + swept_cases definition, live aging bucket, case-open dedupe includes PAYMENT_PROMISED, write-off weights/leftover rule, reconciliation scope to year's accounts, abs() on write-off debits in expected figure.

No remaining PRD-vs-implementation divergence was found in envelope/meta shapes, serializer field sets, endpoint table coverage, RBAC, clock semantics, or the waiver/proration/installment rounding pins, all of which already matched verbatim.
