# Worklog — task_0152_insurance_agency_management

## Step 1: Create task directory — 2026-06-04T18:41:50.000Z

Created `tasks/task_0152_insurance_agency_management/` and its `workspace/` subdirectory (pre-allocated path per orchestration override #1; no auto-scan of ./tasks). Verified `./INSTRUCTION.md` and skills exist.

## Step 2: Generate scaffold (Expert difficulty) — 2026-06-04T18:41:50.000Z

All three files written to task dir; parse cleanly, pass generator lint + self-checks.

### Statistics
- **Entities: 13** — Carrier, Product, Producer, License, Appointment, Account, Policy, CommissionSplit, TrustAccount, TrustLedgerEntry, CommissionStatement, RenewalTask, SystemClock
- **State machines: 5** — Carrier, Appointment, Policy (8 states with a CANCELLED→REINSTATED reinstatement cycle), RenewalTask (cyclic OFFERED→REVIEW re-quote loop), CommissionStatement (FINALIZED→OPEN revert edge)
- **Calculations: 3** — `return_premium` (dual-variant pro-rata vs short-rate), `producer_commission_accrual` (tiered + term-kind branch + Product→Carrier rate fallback), `commission_statement_rollup` (round-per-line-then-sum, OPEN-live vs FINALIZED-frozen)
- **Validations: 23** (ordered, 8 categories)
- **Endpoints: 58** (11 create, 22 action/state-transition, 25 GET incl. FK reverse-reachability, 1 `/_clock` test-driving)
- **Error catalog: 22** (all referenced by a validation or concurrency rule)
- **Roles: 4** — AgencyAdmin, Producer (entity_backed), AccountManager, TrustAccountant (peer-role model)
- **Concurrency rules: 2** — both OCC-on-parent-version (split-create-stale-policy, ledger-post-stale-trust)

### Design statistics
- **§1.8 Difficulty: 18 instances** — exactly 2 per each of the 9 §0.5 rules.
- **§1.9 Corner: 50 instances** (42 active + 8 `excluded_because` stubs) spanning all 9 claim-extraction-guide sections.

### Lint / self-check verdict
- `scaffold_lint.py`: VERDICT clean lint — 622 calls scanned, all conform to §1.5; all 16 §1.1 FKs have reverse-reachability.
- All self-checks pass (error-catalog fully referenced; concurrency vocabulary clean; instance names unique; file-split honored; FK descriptions canonical; enums closed).
- Endpoint count 58 > Expert 20–32 band: overage is mechanical (25 GETs from 13-entity FK reverse-reachability; 22 POSTs from 5 state machines). Density is Expert; trimming GETs would break reverse-reachability. Accepted per §0.4 + lint-clean FK constraint.

## Step 3: Copy INSTRUCTION.md — 2026-06-04T19:11:50.000Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-06-04T19:17:53.000Z

Generated `workspace/PRD.md` (281 lines, ~6,880 words). Did NOT read the two withheld design files.

Sections: §1 Introduction; §2 Global Specs (2.1 RBAC, 2.2 API Response verbatim, 2.3 Pagination, 2.4 Common Props/Identity, 2.5 Resolution, 2.6 Premium-Trust Ledger Principle, 2.7 Monetary Precision/Rounding, 2.8 Uniqueness, 2.9 OCC, 2.10 Validation Ordering, 2.11 Authoritative Clock); §3 Business Logic (3.1–3.10 covering carriers/products, producers/licenses/appointments, accounts/policy, bind/activate/accrual, commission splits, cancellation/return-premium/chargeback, reinstatement, renewal pipeline, trust accounting, commission statements); §4 Endpoint Definitions (58 rows); §5 Error Catalogue (22 errors).

Contracts: Contract 1 (Field-Name Coverage) PASS — 51/51 entity fields, 48/48 params (added to_iso8601 to §2.11). Contract 2 (Rule Coverage) PASS — all 22 error IDs + 49 state/enum values surface; both OCC rules; validation ordering; return-premium dual variant; tiered accrual; statement rollup; all cross-entity cascades. Contract 3 (§3 Path Purity) PASS — 0 path/method leaks in §3. §2.2 byte-identical to source.

## Step 5: Generate unit tests — 2026-06-04T19:44:57.000Z

8 test files (+conftest.py), 78 tests total. All collect cleanly, compile against framework.
- Queue A (Difficulty): 36 tests / 18 instances (all 9 rules × 2, each covered by exactly 2 tests, 0 skipped). Files test_01..test_04.
- Queue B (Corner): 42 tests / 42 non-stub instances (1 test each). Files test_05..test_08.
- SKIPPED: 8 corner instances — all `excluded_because:` stubs whose cited difficulty instance owns the assertion (cancel_already_cancelled_returns_invalid_state, requote_increments_count, return_premium_dual_variant, statement_round_per_line, license_overlap_violation, carrier_not_active_on_bind, renewal_term_not_adjacent_error, cascade_policy_cancel_trust_balance). No PRD-filter skips.
- test_helpers/ (9): __init__, types, api_client, api_errors, assertions, factories, constants, test_users, fixtures.
- Audits: 78 funcs ↔ 78 Design tags (parity); 86 docstring PRD quotes verbatim-matched; no skip/xfail; TrustLedgerEntry/SystemClock omit updated_at/version; Producer identity threaded via make_producer_headers; numeric expectations independently recomputed; clock set explicitly before every windowed op.

## Step 6: Generate implementation — 2026-06-04T19:44:57.000Z

Python+Flask impl at workspace/implementation/. 17 source files + start.sh + requirements.txt.
- Files: app.py, errors.py, response.py, db.py, clock.py, middleware.py, util.py, serialize.py; services/{calculations,derived,trust}.py; routes/{carriers,products,producers,licenses,appointments,accounts,policies,commission_splits,trust_accounts,commission_statements,renewal_tasks,clock_routes}.py.
- Endpoints: 58 (33 POST incl /_clock/set_current_utc, 25 GET) — matches scaffold.
- State machines (Carrier, Appointment, Policy CANCELLED→REINSTATED, RenewalTask cyclic OFFERED→REVIEW, CommissionStatement FINALIZED→OPEN) with preconditions + cross-entity cascades.
- Calculations via Decimal ROUND_HALF_UP: dual-variant return premium (NON_PAYMENT forces pro-rata), tiered accrual (1.00/1.05/1.10, 500000-cent top-tier boundary, Product-override-else-Carrier rate by term_kind), statement rollup (round-per-line, OPEN live / FINALIZED-PAID frozen).
- OCC: expected_<entity>_version checked after state-eligibility, before business effects; parent version bump on split-create + ledger-post. Validation ordering per §2.10.
- Derived at read time: License.status, Account.active_policy_count, TrustAccount.balance_cents, OPEN statement figures.
- start.sh reads $PORT (default 10000), binds 0.0.0.0, foreground exec python3 app.py, pip install guarded by `import flask` sentinel. In-memory dicts only, no seeding (fresh boot total_count:0). App binds socket itself with retry loop + hands fd to make_server (handles same-port bind race).

## Step 7: Test and iterate — 2026-06-04T19:53:50.000Z

Clean 8-round parallel sweep — all rounds 78/78 passing (verified results.{1..8}.json: passed=78, failed=0 each).

**Iterations run:** 2 (baseline sweep + 1 fix-and-verify sweep). Initial sweep showed 2 stable (non-flaky, all-8-rounds) failures. Both fixed; second sweep fully green.

**Tests deleted:** None. Both failures were genuine bugs (one test, one impl); neither PRD-silent nor non-derivable.

**Fixes applied to test_suite/ (1):**
- `test_01_commission_and_return_premium.py` — `TestCommissionTierBoundary.test_at_boundary_500000_uses_top_tier`. TEST BUG (STEP 2). Fixture advanced clock to 2026-03-01 before activating the 500000-cent policy, so activated_at fell outside statement period [2026-02-01, 2026-02-28); per PRD §3.10 the impl correctly excluded it (gross=0). Fixed fixture ordering to activate while clock at 2026-02-01 (inside period), then advance to 2026-03-01 only to read the statement (mirrors passing sibling test_below_boundary_499999). Impl verified returns correct 110000.

**Fixes applied to implementation/ (1):**
- `routes/renewal_tasks.py` — `create_renewal_task()`. IMPL BUG (STEP 3). Policy-state eligibility check ran before duplicate-non-terminal-task check; since first renewal task moves policy to PENDING_RENEWAL, a second create returned ERR_INVALID_STATE instead of PRD-mandated ERR_DUPLICATE_RENEWAL_TASK. PRD §3.8 verbatim names the "second task" scenario as ERR_DUPLICATE_RENEWAL_TASK (409). Reordered to window-open → duplicate-task → state-eligibility. Verified: second task now returns 409 ERR_DUPLICATE_RENEWAL_TASK; window-boundary tests remain consistent.

No flakiness surfaced — both failures deterministic across all 8 rounds.

## Step 8: Finalize PRD — 2026-06-04T19:56:54.000Z

Produced `workspace/PRD_FINALIZED.md` (cp of PRD.md + minimal patch). PRD.md=281 lines, PRD_FINALIZED.md=281 lines (one paragraph modified in place at §3.8 line 169; 0% line-count delta, +2 sentences).

**Changes (1):**
- §3.8 — insert — pinned renewal-task creation check order (window → duplicate → state-eligibility), making explicit that ERR_DUPLICATE_RENEWAL_TASK precedes ERR_INVALID_STATE and overrides §2.10's generic state-before-business sequencing — routes/renewal_tasks.py:43,51-53,56-57.

**Step 7 diff dispositioned:**
1. test_01 fixture-ordering bug → NO PRD edit (impl already matched PRD §3.10; pure fixture bug).
2. renewal_tasks.py validation-ordering → PRD edit applied (genuine under-determination: §3.8 named all three constraints but not precedence; §2.10 generic rule would order state before business, opposite of impl).

Pre-edit search log (edit 1): (a) subject = check ordering in create_renewal_task (duplicate & window precede state; relative position of the three error_ids); (b) read routes/renewal_tasks.py L31-71, grepped ERR_DUPLICATE_RENEWAL_TASK + ERR_RENEWAL_WINDOW_CLOSED across impl (appear only in errors.py + this fn), errors.py:60-61, PRD §2.10 L109, §3.10 L185, confirmed no expected_*_version guard; (c) scoped override to "this creation" + framed as overriding generic §2.10 rather than restating it globally; included window in stated order to match impl exactly.

## Step 9: Complete PRD — 2026-06-04T20:03:49.000Z

Produced `workspace/PRD_COMPLETED.md` (cp of PRD_FINALIZED.md + full impl-scan patch). PRD_FINALIZED.md=281 lines/49,608 chars; PRD_COMPLETED.md=281 lines/51,294 chars; char delta +1,686. 9 inline edits, no new sections/paragraphs.

**Counts:** 9 ambiguity-pins, 0 mismatch-revisions. (Formulas, error codes, calculations, ordering, CRUD shapes already matched impl; every edit pins a prose-silent behavior.)

**Per-change log:**
- §3.1 Carriers — insert — ambiguity — terminate carrier with ACTIVE/PENDING_RENEWAL/REINSTATED policy → ERR_INVALID_STATE (409) — routes/carriers.py:114
- §3.2 Appointments — insert — ambiguity — approve when carrier/producer not ACTIVE → ERR_INVALID_STATE (409) — routes/appointments.py:78,80
- §3.4 Binding/Activation — insert — ambiguity — activate before effective_date → ERR_INVALID_STATE (409) — routes/policies.py:180
- §3.6 Cancellation — insert — ambiguity — RETURN_PREMIUM_REFUND ledger entry + account version bump only when state trust account exists AND return premium non-zero — routes/policies.py:223-226
- §3.7 Reinstatement — insert — ambiguity — reversing PREMIUM_RECEIPT + version bump only when state trust account exists AND prior refund non-zero — routes/policies.py:261-264
- §3.8 Renewal pipeline — insert — ambiguity — first advance IDENTIFIED→REVIEW on non-PENDING_RENEWAL policy → ERR_INVALID_STATE (409); advance/re-quote/completion/loss require expected_renewaltask_version (non-optional) — routes/renewal_tasks.py:106,111,125,140,197
- §3.8 Renewal completion — insert — ambiguity — completion on non-PENDING_RENEWAL → ERR_INVALID_STATE (409); successor download_source=MANUAL; successor inherits account_id/product_id/writing_producer_id/state_code from prior, premium/dates from request — routes/renewal_tasks.py:144-176
- §3.8 Expire/Non-renew — insert — ambiguity — expire before expiration_date → ERR_INVALID_STATE (409) + requires expected_policy_version; non-renew when no renewal task is LOST → ERR_INVALID_STATE (409) — routes/policies.py:280-283,299-305
- §2.11 Authoritative Clock — insert — ambiguity — clock-set success → 200 OK with data.current_utc as 3-fractional-digit ISO 8601 UTC — routes/clock_routes.py:22

Left unchanged (already pinned): commission tier/rate/rounding, dual-variant return premium, statement rollup & freeze, license overlap (half-open) & validity, RBAC table, OCC ordering, pagination/envelope, uniqueness errors.

---

## PIPELINE COMPLETE — 2026-06-04T20:03:49.000Z

All 9 steps done. Final 8-round parallel sweep: 78/78 passing every round (results.{1..8}.json all passed=78 failed=0). Task task_0152_insurance_agency_management is green and finalized.
