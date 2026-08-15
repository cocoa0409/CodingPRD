# Worklog — task_1759_merchant_chargeback_representment

## Step 1: Create Task Directory — 2026-08-14T14:07:00.000Z

Task directory `tasks/task_1759_merchant_chargeback_representment/` and `workspace/` subdirectory pre-created and pre-assigned by the invoking pipeline. Step 1 treated as DONE per command args; no index scan performed.

## Step 2: Generate Scaffold — 2026-08-14T15:19:00.000Z

Done. All three scaffold artifacts are written and the lint verdict is clean.

### Files written
- `SCAFFOLD.yaml` — §1.0–§1.7 (no design keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level `scaffold_difficulty_design:`
- `SCAFFOLD_CORNER_DESIGN.yaml` — single top-level `scaffold_corner_design:`

### Counts
| Element | Count |
|---|---|
| Entities | 14 (Merchant, ReasonCodeRule, Transaction, Chargeback, EvidenceItem, Representment, FeeAssessment, ReserveAccount, ReserveLedgerEntry, RatioSnapshot, ProgramEnrollment, RemediationPlan, PreventionAlert, EducationAssignment) |
| Endpoints | 56 (incl. `POST /acquirer/ops/advance-month` sweep, `POST /acquirer/_clock/set_current_utc` with pinned startup default `2026-08-01T00:00:00Z`, batch transaction ingest, win-rate computed read; 12 of the GETs exist to satisfy FK reverse-reachability) |
| Error codes | 35 (two initially-drafted errors — `ERR_CURE_NOT_AVAILABLE`, `ERR_ALERT_DEADLINE_PASSED` — were provably unreachable and removed) |
| Calculations | 8 (incl. dual-variant `chargeback_ratio` POSTED/GROSS and `reserve_target` FIXED_TIER/EXPOSURE_BASED) |
| State machines | 9 (Chargeback has parallel `case_status` × `funds_status` axes plus a DECIDED_WON→PRE_ARBITRATION→… cycle; Representment and RemediationPlan carry resubmission cycles; EvidenceItem cycles DRAFT↔ATTACHED) |
| Validations | 11 priority tiers (auth → role → existence → OCC → state → safety → constraint → temporal → referential → fiscal → payload shape) |
| Roles | 4 (MerchantUser is `entity_backed:Merchant` with cross-merchant 404-hiding; FinanceOps has X-User-ID-keyed segregation of duties on fee waiver) |
| Difficulty instances | 22 (all 9 rules; rules 2, 3, 6, 7 carry a third instance; rule 2 covers all three modes a/b/c) |
| Corner instances | 60 entries (52 active + 8 `excluded_because` stubs), across all nine guide sections |
| Lint | `VERDICT: clean lint` — 770 structured calls scanned, 0 violations, all 17 FKs reverse-reachable |

### Notable design decisions
- **Archetype blend**: compliance/audit primary, ledger-reconciliation secondary; flat topology, cyclic state shape, segregation-of-duties role model, immediate consistency.
- **Every numeric assert is pre-computed**: e.g., ratio 90 bps exactly (9/1000) enrolls while 80 bps (8/1000) does not; reserve holds round per-entry (33+33=66) while the target rounds once (67) — the deliberate 66-vs-67 split is a trap for wrong rounding order; fine escalation 250000→375000 keys off the *post-increment* `months_over_count`.
- **Two genuinely different interval semantics** for Rule 8: half-open ReasonCodeRule effective windows (adjacency legal) vs closed month ranges on ProgramEnrollment (re-enrolling in the exit month itself conflicts).
- **Two OCC rules** on the sanctioned parent-version pattern (representment create on `Chargeback.version`, reserve-policy patch on `Merchant.version`), each with stale-version tests that also outrank competing business errors per the priority table.
- **Compensating invariants** on two different conserved quantities: clearing money (WON→pre-arb→LOST nets exactly to the accept path) and reserve units (`held_cents == ΣHOLD − ΣRELEASE − ΣFORFEIT` through the full litigation round-trip).
- All expiry is driven by the logical-clock endpoint (no wall-clock waits); the deadline semantics are inclusive and the expiry sweep deliberately covers only `{RECEIVED, MERCHANT_NOTIFIED}` so the past-deadline submit error stays reachable on REPRESENTED cases.

## Step 3: Copy Shared Files — 2026-08-14T15:19:30.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1759_merchant_chargeback_representment/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-14T15:42:00.000Z

All contracts pass. The PRD is complete and verified.

### Summary

**Output file:** `workspace/PRD.md` (7,588 words, 307 lines)

**Section list:**
- §1 Introduction (2 paragraphs, business-context angle)
- §2 Global Specifications (9 subsections): 2.1 RBAC, 2.2 API Response Structure (byte-identical verbatim block — verified), 2.3 Pagination, 2.4 Common Resource Properties, 2.5 Logical Clock & Inclusive Deadlines, 2.6 Monetary Precision/Basis Points/Rounding, 2.7 Existence Validation & Merchant Data Hiding, 2.8 OCC, 2.9 Validation Priority Order
- §3 Business Logic & Workflows (9 subsections, chronological-timeline grouping): merchant onboarding/suspension/reserve policy → reason-code rules → settlement ingest & rolling reserve → prevention alerts → chargeback receipt/notify/accept → evidence & representment packet → network outcomes/pre-arbitration/reversal → fees → monthly sweep/program enforcement/win-rate analytics
- §4 Endpoint Definitions (56 rows, 4 columns only)
- §5 Error Code Catalogue (35 rows, 2 columns only)

**Coverage audit (hard contracts):**

```
Field coverage check (Contract 1):
- entities[].fields + endpoint inputs/query/path params: 104 required, 104 present, 0 missing
- enum/state values: 84 required, 84 present, 0 missing
- error ids: 35 required, 35 present in §2/§3 narrative + §5 table, 0 missing
Status: PASS (2 gaps found in pass 1 — module_code, WAIVED — repaired; pass 2 clean)

Rule coverage check (Contract 2):
- validations[] with priority: 11 checked, 11 expressed in the §2.9 ordered list (incl. payload-shape deliberately last; ERR_SEGREGATION_OF_DUTIES called out as 403 inside the 409 tier), 0 missing
- concurrency_rules[] OCC: 2 checked, 2 expressed (expected_chargeback_version on representment create, expected_merchant_version on reserve-policy patch; both ERR_STALE_VERSION/412; stale-read framing only, no race language), 0 missing
- state_machines[].transitions: 40 checked, 40 fully expressed with preconditions+error ids+side effects (incl. HIGH_RISK ledger cascades with exact source_kind values, cure_count lineage rule, EXPIRED/REVERSED multi-source transitions), 0 missing
- calculations[]: 8 checked, 8 fully expressed as reconstructible prose (3 inclusive deadlines, POSTED/GROSS ratio with 100,000-bps sentinel, pinned per-entry rounding, both reserve-target variants with closed 90-day window and ×2 exposure, release waterfall, 4 program threshold pairs, pinned fine order with already-incremented months_over_count and 1.0/1.5/2.0 tiers, half-win win-rate), 0 missing
- endpoints[].side_effects / applies_to: 56 checked, all side-effect-bearing endpoints narrated, 0 missing
- entities[].fields[] structured content: all defaults/initials/nullability reconstructible from prose, 0 missing
- sibling-branch symmetry: 7 groups checked (EXPIRED ×2, REVERSED ×3, pre-arb WON/LOST, plan APPROVE/RETURN, alert REFUND/DISMISS, VISA/MC tiers, settle/waive), all equal density
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 684
- tokens starting with `/`: 0; bare HTTP-method tokens: 0; method+path combos: 0
Status: PASS
```

One authoring defect was caught and fixed during audit: a garbled sentence in §3.4 briefly named a nonexistent `ACTIONED_REFUNDED` state; corrected to the scaffold's `ACTIONED_REFUND`. The withheld difficulty/corner design files were never opened.

## Step 5: Generate Unit Tests — 2026-08-14T16:25:00.000Z

All checks pass. Final report:

### Files written

**`test_helpers/`** (Stage 1)
- `types.py` — 27 enums, 14 entity TypedDicts; `ReasonCodeRule`/`ReserveLedgerEntry`/`RatioSnapshot` correctly omit `updated_at`/`version` (immutable per PRD §2.4)
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per each of the 40 PRD endpoints
- `api_errors.py` — all 35 `ApiErrorId` members + HTTP map registered via `set_error_http_status_map`
- `assertions.py` — per-entity assertions, `parse_instant`/`assert_instant_equal` (second-precision instant compare, avoiding serialization over-pinning), `assert_reserve_ledger_fold`
- `factories.py`, `constants.py` (72h alert window, 100000 sentinel bps, program thresholds/fine bases, MAX_CURES), `test_users.py` (opaque-role constants + `make_merchant_user_headers` builder for the entity-backed role), `fixtures.py` (tiers 1–5: rule/merchant/case pipelines, packet assembly with fresh OCC token, decided-case shortcuts, over-threshold/clean month drivers, exited-enrollment fixture), `__init__.py` barrel

**`test_suite/`** (Stage 2) — `conftest.py` + 8 files: `test_01_merchants_access_and_envelope.py` (7), `test_02_settlement_reserve_target.py` (10), `test_03_reserve_release.py` (7), `test_04_chargeback_receipt_deflection.py` (13), `test_05_case_lifecycle_prearb.py` (13), `test_06_evidence_representment.py` (17), `test_07_fees_and_analytics.py` (6), `test_08_sweep_programs_remediation.py` (20).

### Test counts
- **Queue A (Difficulty): 42 tests** — 21 of 22 instances × 2 tests each
- **Queue B (Corner): 51 tests** — 51 of 52 non-stub instances × 1 test each; all 8 `excluded_because:` stubs left untranslated with cross-references verified to resolve
- **Total: 93 tests**, collected cleanly by pytest

### Skipped instances (two-condition reason)
1. **`Difficulty/combinatorial_formula/program_fine_uses_post_increment_months_over`** — fails *unique derivability*. The instance asserts an `ECM` enrollment and a 375000 month-4 fine, but its setup (10 chargebacks / 100 sales = 1000 bps, count 10 on MASTERCARD) matches both ECM (≥150, ≥10) and HECM (≥300, ≥10), and PRD §3.9 pins "the higher tier wins when both match" plus "500,000 cents for `VDMP_EXCESSIVE` and `HECM`" — the PRD-derived outcome is HECM with a 750000 month-4 fine. The asserted outcome contradicts the contract.
2. **`Corner/validations/open_chargeback_per_transaction_gate`** — fails *unique derivability*. After the first chargeback receipt the transaction is `CHARGED_BACK`, and PRD §3.5's own governing order checks "the transaction must be `SETTLED` … fails with `ERR_TRANSACTION_NOT_CHARGEBACKABLE`" before the open-case gate (§2.9 ranks state at priority 5 ahead of structural at 7); the asserted `ERR_TRANSACTION_HAS_OPEN_CHARGEBACK` (leg 1) and post-reversal success (leg 2) rely on a "rejects only REFUNDED" reading that appears only in the instance's note, not in the PRD.

Faithful-translation repairs inside otherwise-valid instances (documented in test comments): `reserve_ledger_append_only` setup reduced to one sale so the asserted 2-row ledger matches (the instance posted two sales but asserted two rows); `occ_stale_reserve_policy_patch_rejected` asserts `version == observed + 1` rather than an absolute value (PRD pins the increment, not the initial value); deadline assertions use instant comparison (PRD pins second-precision arithmetic, not the string format); the education-cascade pair is asserted as a set (PRD does not pin creation order).

### Self-audit results
- **Stage 1**: compiles; imports cleanly with the framework on `PYTHONPATH`; identity threading verified (all ownership-gated calls use `make_merchant_user_headers(merchant["id"])`); fixtures use `get_success_data`
- **Stage 2**: all 93 docstrings carry exactly one `Design:` line resolving to a real instance (0 orphans, 0 dual/untagged); every docstring contains a ≥8-word verbatim PRD span surviving `grep` (93/93); no `skip`/`skipif`/`xfail` anywhere; no scaffold/table references in comments or docstrings; asserted `error_id`s all named in PRD prose; priority-order tests (`submit_state_outranks_temporal`, `release_safety_outranks_fiscal`, OCC-ahead-of-structural) rest on the explicit PRD §2.9 order, not scaffold silence

## Step 6: Generate Implementation — 2026-08-14T16:26:00.000Z

All verification complete. Summary of the delivered implementation:

### Files written (all under `workspace/implementation/`)

- `start.sh` — guarded launcher (`pip install` only if flask missing), `exec python3 app.py`, foreground, `0.0.0.0:$PORT` (default 10000)
- `requirements.txt` — Flask==3.1.3
- `app.py` — app factory, blueprint registration, envelope-shaped 404/405/exception handlers
- `db.py`, `clock.py` — empty-on-boot in-memory store; logical clock starting at exactly `2026-08-01T00:00:00Z`
- `errors.py` — all 36 catalog error IDs with their HTTP statuses
- `response.py` — envelope: `meta{api_request_id (req_*), api_request_timestamp}` + `response_type` + `data`; list meta adds `limit/offset/total_count/has_more`
- `middleware.py` — `X-User-ID`/`X-User-Role` auth (401) and per-endpoint RBAC (403)
- `util.py` — enum member sets, ISO8601 parse/format (3 fractional digits, Z), `Decimal` ROUND_HALF_UP helpers, deferred payload validation (`Body`), pagination (limit default 10/min 1/max 100, offset 0)
- `records.py`, `serializers.py` — factories and per-entity serializers; immutable types (ReasonCodeRule, ReserveLedgerEntry, RatioSnapshot) carry only `id`/`created_at`
- `routes/` (14 blueprints) — all 44 endpoints from the endpoint table
- `services/` — `reserve.py` (per-transaction ROUND_HALF_UP holds, held_cents fold, FIXED_TIER/EXPOSURE_BASED target, release waterfall), `cascade.py` (win/loss/pre-arb/reversal/expiry cascades), `sweeps.py` (expiry sweep + advance-month: ratio snapshots with 100000 zero-denominator sentinel, POSTED/GROSS bases, tier thresholds, tiered fines from the already-incremented months_over_count, education cascade)

### Coverage notes

- **State machines**: all transitions for Merchant, Chargeback (both axes, incl. DECIDED_WON↔PRE_ARBITRATION cycle), Representment (incl. single-cure lineage with cure_count carry), EvidenceItem (cyclic DRAFT↔ATTACHED), FeeAssessment (SoD waiver), ProgramEnrollment, RemediationPlan (RETURN resubmit cycle), PreventionAlert, EducationAssignment
- **Calculations**: deadline arithmetic (inclusive), chargeback ratio (round-half-up bps, sentinel), reserve hold rounding (per-entry first), reserve target (closed 90-day window, EXPOSURE_BASED max), releasable-reserve waterfall, program thresholds/fine tiers, win-rate with PARTIAL_WON half credit (null on empty)
- **Validation priority** per PRD §2.9: auth → role → existence (with MerchantUser hidden as 404) → OCC (412) → state → compliance → structural → deadline → referential (422) → funds → payload shape last
- OCC on both guarded writes (`expected_chargeback_version`, `expected_merchant_version`); no seeding anywhere at startup

### Boot smoke test

`bash start.sh` boots in ~2s on both a custom `$PORT` and the default 10000. Five probe suites (roughly 90 assertions) all passed against fresh boots: happy path (rule→merchant→txn→chargeback→notify→evidence→OCC representment→submit→WON→pre-arb→LOST→sweep), HIGH_RISK holdback hold/release/forfeit with exact cents, cure-limit and partial-win validation, reversal with fee survival, fee settle/waive + SoD 403, suspension gates, force-scoping, sweep-driven VDMP enrollment + education + 250000 fine + reserve lock, remediation cycle + exit review, release waterfall, clock-driven alert/chargeback expiry with packet supersede, batch ingest, and pagination meta. Every probe failure encountered during testing traced to a probe-side expectation bug; each one reconfirmed the implementation matched the PRD (e.g., OCC 412 preceding ALREADY_OPEN 409, sticky target across release, irreversible expiry).

## Step 7: Run Tests and Iterate — 2026-08-14T16:35:00.000Z

Clean 8-round sweep: all rounds 93/93 passed. Exiting with the summary.

---

### Summary

**Iterations run:** 2 (sweep 1: 2 deterministic failures in all 8 rounds; fixes applied; sweep 2: all 8 rounds 93/93 passed).

**Tests deleted:** None.

**Fixes applied to `test_suite/`:**

1. `test_suite/test_05_case_lifecycle_prearb.py` — added `setup_case` to the `from test_helpers import (...)` list. `test_expiry_from_received_without_notify` called `setup_case(...)` but only `setup_decided_case`/`setup_notified_case`/`setup_submitted_case` were imported, producing a deterministic `NameError`. The asserted rule (clock set past `representment_due_at` → case `EXPIRED`, `funds_status` `DEBIT_FINAL`, `is_ratio_counted` stays true) is verbatim PRD §3.5/§3.9; the test was faithful, just missing the import.

2. `test_suite/test_07_fees_and_analytics.py` — `test_partial_win_requires_amount_and_recredits_partial` now passes `merchant_overrides={"reserve_rate_bps": 0}` into `setup_submitted_case`. The test's arithmetic comment ("Sale +10000, receipt debit −10000, partial re-credit +6000 → clearing 6000") ignored that the fixture merchant carries the PRD §3.1 default `reserve_rate_bps=500`, so the sale correctly credits clearing net of the 500-cent reserve hold (PRD §3.3: "credits the merchant's `clearing_balance_cents` by the sale amount net of the per-transaction reserve hold"). The implementation was PRD-correct (9500 − 10000 + 6000 = 5500); the test setup failed to pin the zero-rate precondition its own assertion assumed.

**Fixes applied to `test_helpers/`:** None.

**Fixes applied to `implementation/`:** None — both failures traced to test-artifact bugs; the implementation matched PRD on every tripped assertion.

**Note on flakiness:** Mid-sweep console output showed interleaved `FAILED` fragments attributed to `test_accept_with_packet_in_flight_rejected` and `test_win_rate_partial_weighting_and_filter`; these were stdout splice artifacts from 8 concurrent pytest processes sharing one terminal, not real failures — all 8 authoritative `results.*.json` files confirmed those tests passed in every round, and the only true failures were the two deterministic ones above.

## Step 8: Finalize PRD — 2026-08-14T16:40:00.000Z

Done. `PRD_FINALIZED.md` created at `workspace/PRD_FINALIZED.md` as an exact byte-for-byte copy of `PRD.md`.

### Summary

**Line counts / %-delta:** PRD.md = 307 lines; PRD_FINALIZED.md = 307 lines; delta = 0%. Zero edits were warranted.

**Per-<step_7_diff>-item justification:**

- **Fix 1 (`test_05_case_lifecycle_prearb.py`, missing `setup_case` import):** Pure test-artifact bug. The asserted behavior — clock set past `representment_due_at` flips a `RECEIVED`/`MERCHANT_NOTIFIED` case to `EXPIRED` with `funds_status` `DEBIT_FINAL` while `is_ratio_counted` stays true — is pinned verbatim by PRD §3.5 ("...becomes `EXPIRED` (terminal), its `funds_status` becomes `DEBIT_FINAL`...") and §3.9 (posted-basis numerator excludes only `REVERSED` cases). Verified the implementation matches the PRD exactly: `implementation/services/sweeps.py:102-104` fires `cascade_expire` on past-due `RECEIVED`/`MERCHANT_NOTIFIED` cases, and `implementation/services/cascade.py:108-116` sets `EXPIRED`/`DEBIT_FINAL`, supersedes `ASSEMBLED` packets, and recomputes the target without touching `is_ratio_counted`. No PRD silence, no mismatch — no edit.

- **Fix 2 (`test_07_fees_and_analytics.py`, added `merchant_overrides={"reserve_rate_bps": 0}`):** Pure fixture-precondition bug. The two behaviors the test tripped on are both PRD-pinned: the `reserve_rate_bps` default of 500 (PRD §3.1: "it defaults to 500 (that is, 5.00%)", impl `routes/merchants.py:28-30`) and the net-of-hold clearing credit (PRD §3.3: "credits the merchant's `clearing_balance_cents` by the sale amount net of the per-transaction reserve hold", impl `services/reserve.py:104-105`: `merchant["clearing_balance_cents"] += txn["amount_cents"] - hold`). The fixture (`test_helpers/fixtures.py:38 create_merchant(**overrides)`) relies on the server default; the test's arithmetic comment only holds at rate 0. Implementation was PRD-correct — no edit.

**Changes list:** None (empty).

**Per-edit pre-edit search log:** No edits were committed, so no pre-edit searches under the NO-NEW-MISMATCH rule were triggered. The mandatory per-item implementation verification searches were performed as documented above (subjects: chargeback expiry cascade and per-transaction reserve hold / clearing credit; paths read: `services/sweeps.py`, `services/cascade.py`, `services/reserve.py`, `routes/transactions.py`, `routes/merchants.py`, plus the two fixed test files and the fixture helpers).

Step 7 applied zero fixes to `implementation/` and deleted zero tests; both failures traced to test-artifact bugs where the PRD already uniquely determined the behavior, so the alignment target (`implementation/`) and the PRD are already in agreement at every site Step 7 touched.

## Step 9: Complete PRD — 2026-08-14T17:15:00.000Z

Done. `workspace/PRD_COMPLETED.md` is written (copied from `PRD_FINALIZED.md`, then edited in place).

**Size:** source `PRD_FINALIZED.md` 307 lines / 57,066 chars → `PRD_COMPLETED.md` 307 lines / 61,330 chars. Char delta +4,264; zero lines added or removed (all edits are in-paragraph inserts/revisions; no new sections).

**Counts:** 31 changes — 31 ambiguity-pins, 0 mismatch-revisions. The implementation proved to be a faithful superset of the PRD everywhere; every divergence was PRD silence, never contradiction.

Changes (all insert/revise — ambiguity):

- §2 intro — insert — state is in-memory, empty on every boot, nothing seeded — `db.py:1-26`, `app.py:1-4`
- §2.1 — revise — whitespace-only header values count as empty (401) — `middleware.py:18`
- §2.2 — revise — `api_request_timestamp` is stamped from the wall clock; logical clock governs only business instants in `data` — `response.py:11-15`
- §2.3 — insert — non-integer/out-of-range `limit` (1–100) or negative `offset` → `ERR_INVALID_REQUEST` 400 — `util.py:246-265`
- §2.4 — revise — `version` starts at 1 on creation — `records.py:17-19`
- §2.7 — revise — MerchantUser force-scoping applies to every merchant-scoped list (evidence, representments, fees, reserve accounts, alerts, enrollments) and win-rate analytics; list filters are predicates (no 404 on no-match); enum filter with non-member → `ERR_INVALID_ENUM` 400 — `analytics.py:21`, `fees.py:62-63`, `enrollments.py:55-56`, `util.py:268-275`
- §2.8 — insert — missing/non-integer OCC version token → `ERR_INVALID_REQUEST` 400, deferred to payload-shape priority 11 — `merchants.py:72-79`, `representments.py:57-64`
- §2.9 item 6 — revise — suspension gate includes AcquirerOps on-behalf evidence/representment actions — `evidence.py:40-43`, `representments.py:71-74,146-148`
- §2.9 item 11 — revise — unrecognized request fields ignored; missing/malformed JSON body treated as empty object — `util.py:105-107`, `routes/common.py:34-35`
- §3.1 — revise — MCC accepted as opaque non-empty string, no four-digit format validation — `merchants.py:25`
- §3.1 — insert — suspend/reinstate are unconditional idempotent writes (re-suspend/re-reinstate succeeds, version still bumps) — `merchants.py:97-112`
- §3.1 — insert — suspension gate keys on the affected merchant, not the acting role (AcquirerOps on-behalf rejected too) — `evidence.py:40-43`, `representments.py:71-74`
- §3.1 — revise — empty reserve-policy patch (neither field) still bumps merchant version and recomputes target — `merchants.py:86-93`
- §3.2 — revise — `required_evidence_types` may be empty (packet then trivially complete) — `rules.py:34,54`
- §3.2 — revise — non-null `effective_to` must be strictly after `effective_from` else `ERR_INVALID_REQUEST` 400 — `rules.py:50-51`
- §3.2 — insert — the covering rule is bound to the case at ingest; its days/fee/evidence-fields govern the case for its whole lifecycle — `chargebacks.py:82-83,139`, `representments.py:153`
- §3.3 — revise — batch `count` ≥ 1; batch is atomic (all refs pre-validated, one duplicate rejects the whole file booking nothing) — `transactions.py:66,77-86`
- §3.3 — revise — `SCHEDULED_RELEASE` entries carry null `release_eligible_at` as well as null `source_id` — `reserves.py:49`
- §3.3 — revise — trailing 90-day sales window counts transactions of any status — `services/reserve.py:56-60`
- §3.3 — revise — target recompute triggers enumerated (receipt, acceptance, decision, pre-arb, reversal, ingest, patch, sweep); runs for STANDARD and HIGH_RISK alike; bumps the account `version` — `chargebacks.py:101-103`, `services/cascade.py:36-41,119-121`, `services/sweeps.py:205-207`
- §3.5 — revise — expiry does not unwind the HIGH_RISK receipt holdback (case-bound HOLD remains posted), unlike a decided loss — `services/cascade.py:108-116`
- §3.6 — revise — representments listable filtered by `chargeback_id` and `status` — `representments.py:113-125`
- §3.6 — revise — withdrawing a non-DRAFT item → `ERR_INVALID_REQUEST` 400 — `evidence.py:79-80`
- §3.8 — revise — manual fee's optional `chargeback_id`/`enrollment_id` are existence-checked only, not required to belong to the same merchant — `fees.py:33-36`
- §3.9 — revise — `period_month` is a zero-padded calendar month 01–12 — `util.py:50,235-240`
- §3.9 — revise — multiple concurrent open enrollments per (merchant, network) each increment and each ACTIVE one is fined; a sweep-created enrollment is fined in its creation sweep at count 1 (face value) — `services/sweeps.py:174-201`
- §3.9 — revise — ratio-pointer refresh and target recompute run for every in-scope merchant, including no-activity ones — `services/sweeps.py:203-207`
- §3.9 — revise — manual enrollment starts ACTIVE with `months_over_count` 1; `enrolled_month` YYYY-MM; null `exited_month` is open-ended in the overlap rule — `records.py:181-192`, `enrollments.py:26`, `services/sweeps.py:87-91`
- §3.9 — revise — APPROVE on an already-REMEDIATION enrollment leaves it REMEDIATION; every review overwrites `reviewed_by_user_id` and `decision_note` (omitted note clears prior) — `plans.py:86-93`
- §3.9 — revise — exit criterion measured on the posted basis (`count_ratio_bps`); `exited_month` YYYY-MM — `enrollments.py:87-92`
- §4 — insert — the monthly checkpoint and clock-set endpoints return 200 OK with their tally/result objects — `ops.py:29,40`
