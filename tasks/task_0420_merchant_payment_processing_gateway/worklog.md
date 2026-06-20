# Worklog — task_0420_merchant_payment_processing_gateway

## Step 1: Create Task Directory — 2026-06-19T08:29:42.000Z

Pre-assigned task directory `tasks/task_0420_merchant_payment_processing_gateway` confirmed present. Created `workspace/` subdirectory. Did NOT scan/auto-increment task index (pre-assigned ID per orchestration instructions). Difficulty for scaffold: Expert.

## Step 2: Generate Scaffold (Expert) — 2026-06-19T09:58:43.000Z

Scaffold package generated across multiple subagent attempts (two died on infra issues: agent#1 "connection closed mid-response" after writing SCAFFOLD.yaml + SCAFFOLD_DIFFICULTY_DESIGN.yaml; agent#2 timed out before writing anything). Final package completed and repaired by orchestrator + a third hardened subagent. Final state: **clean lint** (`scaffold_lint.py` VERDICT: clean lint; 50 endpoints, 12 entities, 18 §1.8 instances, 51 §1.9 instances, 565 calls scanned).

Expert-band counts (SCAFFOLD.yaml §1.1–§1.7): entities=12 (band 10-15 ✓), endpoints=50 (exceeds 20-32 guideline — kept, reflects the scenario's 8 genuine subsystems: fee-plans, merchant onboarding/underwriting, charges auth/capture/void, refunds, settlement batches, reserve/rolling-hold, payouts, ledger, 1099-K, disputes/representment, webhooks), errors=23 (band 18-30 ✓), state_machines=7 (band 4+ ✓), calculations=5, validations=19, roles=4. §1.8 difficulty design = 9 rule_ids × 2 = 18 instances. §1.9 corner design = 51 real + 13 `excluded_because:` stub instances across all 9 taxonomy sections.

Repairs applied by orchestrator (the agents' generated YAML had defects):
1. **YAML quoting (deterministic fix script):** quoted 53 optional-field `?` tokens in SCAFFOLD.yaml flow sequences (e.g. `input: [a, "b?"]`) and 20 bracket-index JSONPaths in SCAFFOLD_DIFFICULTY_DESIGN.yaml captures (e.g. `{ rr_id: "$.data[0].id" }`) — without these the files did not parse with PyYAML.
2. **Endpoint-reference bug (lint check a, 19 violations):** every §1.8 recipe used `POST /merchants/{id}/risk-reviews` to obtain the underwriting review, but §1.5 has no such create endpoint — `POST /merchants` auto-creates an OPEN RiskReview, and the id is fetched via `GET /merchants/{id}/risk-reviews` (`$.data[0].id`). Changed all 19 bare-list calls `POST`→`GET`; the 19 `/{rid}/approve|reject` POSTs were left intact.
3. **api_prefix bug (lint check f, 13 FK_REVERSE_UNREACHABLE):** `api_prefix` was `/merchants`, but this scaffold uses a flat top-level path structure (`/merchants`, `/fee-plans`, `/charges`, … all at root), so the linter's segment-derivation returned `{}` and flagged every FK. Set `api_prefix: ""` (correct for the flat layout; api_prefix is metadata only — impl/test generators use endpoint `path:` values directly). All 13 FKs then resolved via existing sub-resource GETs (`GET /merchants/{id}/{charges|payouts|risk-reviews|...}`) and filtered lists.

Corner-design subagent summary (verbatim): instances by section — Entities 11 real/0 stub; State Machines 8/1; Calculations 4/3; Validations 9/4; Endpoints 5/0; Errors 4/2; RBAC 5/1; Cross-Cutting 4/2; Consistency Model 1/0. Total 51 real + 13 stub; all 64 names unique across both design files.

## Step 3: Copy INSTRUCTION.md — 2026-06-19T09:59:16.000Z

Copied `INSTRUCTION.md` (1424 bytes) from project root to `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-06-19T10:07:44.000Z

PRD generated at `workspace/PRD.md` (293 lines). Subagent confirmed full coverage and passed the doc-generator's three hard contracts. Verbatim subagent summary:

Generated workspace/PRD.md — 294 lines — for the Merchant Payment Processing Gateway domain.
Major sections: §1 Introduction (3 paragraphs); §2 Global Specifications (2.1 RBAC + identity translation, 2.2 Response Structure verbatim block, 2.3 Pagination, 2.4 Common Properties & Versioning [full-property entities vs LedgerEntry/WebhookEvent id/created_at only], 2.5 Ledger as Single Source of Truth, 2.6 Cascading Effects, 2.7 Nested Path Validation, 2.8 Request Validation & Enumerations, 2.9 State Discipline & Validation Priority, 2.10 OCC on Batch Settlement); §3 Business Logic (12 subsections: fee plans, onboarding/underwriting, charge auth/capture/void, dual-variant processing-fee calc, refunds, disputes & representment, settlement pipeline, settlement-summary calc, rolling reserve, payouts, ledger/1099-K/webhooks, logical clock); §4 Endpoint Definitions (4-col table); §5 Error Code Catalogue (2-col table).
Coverage (verified programmatically): all 50 §1.5 endpoints in §4; all 23 §1.6 error IDs in §2/§3 prose + §5 table; all §1.2 state values/transitions (Merchant, Charge parallel auth/settlement axes, Refund, Dispute cyclic, SettlementBatch, Payout, ReserveEntry); all 5 §1.3 calculations (processing_fee FLAT vs INTERCHANGE_PLUS round-then-sum + volume tier; settlement_summary sum-then-round reserve; chargeback_ledger_impact open-then-won drift; tax_1099k_gross strict-> threshold; merchant_balance_recompute) with constants embedded (interchange 165/10 bps, reserve 500/1000 bps, T+1/T+2, 90-day reserve, 7-day auth, 14-day evidence, 2-round cap, 250000 threshold, high-risk MCC set).
Hard Contracts: Contract 1 (Field-Name Coverage) 61/61 entity fields + 45/45 endpoint params PASS; Contract 2 (Rule Coverage) 19/19 validations with priority ordering + OCC rule (expected_merchant_version + ERR_STALE_MERCHANT_VERSION/412) + transitions + 5 calcs + cascades PASS; Contract 3 (§3 Path Purity) 418 §3 backtick tokens, 0 violations PASS.

## Step 5: Generate Unit Tests — 2026-06-19T10:31:53.000Z

Verbatim subagent summary:

Generated complete test infrastructure for task_0420 (Merchant Payment Processing & Gateway).
Test files: 9 (8 test modules + conftest.py): test_01_fee_pricing.py, test_02_settlement_and_reserve.py, test_03_disputes.py, test_04_charge_lifecycle.py, test_05_balances_and_cascades.py, test_06_temporal_and_tax.py, test_07_underwriting_and_occ.py, test_08_resources_and_rbac.py, conftest.py.
Total tests: 89 (all collect cleanly under pytest; all pinned arithmetic re-derived and matches the design indices verbatim).
Queue A (§1.8 Difficulty): 38 tests covering all 18 instances across 9 rules, each with ≥2 tests (no shortfalls).
Queue B (§1.9 Corner): 51 tests covering all 51 non-stub instances, each with ≥1 test.
Instances SKIPPED: 0. Every non-stub instance passed the PRD-first two-condition filter. The 13 excluded_because corner stubs were correctly NOT translated; all 13 difficulty_instance cross-references resolve to real §1.8 names.
test_helpers/ files written (9): __init__.py (barrel export), types.py (entity TypedDicts; LedgerEntry/WebhookEvent carry only id+created_at), api_client.py (one method per §1.5 endpoint, full root paths), api_errors.py (23 error IDs + HTTP status map), assertions.py, factories.py, constants.py, test_users.py (entity-backed MerchantUser builder + opaque operator constants), fixtures.py (tiered composite setup: fee plans → approved merchant → captured charge → settle → fund → dispute/refund chains).
Verification: all 89 docstrings end with exactly one Design: tag; every quoted citation verbatim-present in PRD.md (fixed 11 C3 ellipsis violations); no scaffold/§1.x/Table-N leakage; no skip/xfail markers; RiskReview obtained via GET /merchants/{id}/risk-reviews ($.data[0].id); flat path structure api_prefix:"" honored.

## Step 6: Generate Implementation — 2026-06-19T10:31:53.000Z

Verbatim subagent summary:

Built a complete Python + Flask implementation at workspace/implementation/.
Files written: start.sh (executable launcher; cd to own dir, guards pip install on a cheap `import flask` check, then exec python3 app.py); requirements.txt (Flask==3.0.3); app.py (all 48 endpoints at flat top-level paths api_prefix:"", error handlers, validation-priority chain auth → forbidden role → ownership → path existence → FK → state → business rules, app.run host 0.0.0.0 port from $PORT default 10000); constants.py (high-risk MCCs, risk-band reserve/funding tables, hold windows, thresholds, interchange rate, enum catalog); errors.py (ApiError + full error catalog with HTTP statuses); response.py (envelope: meta api_request_id req_…, ISO-8601 ms timestamp, limit/offset/total_count/has_more on lists; response_type object/array/error; data); db.py (in-memory store + logical clock); common.py (record lifecycle, system fields, version bumps, serialization, Decimal round-half-up cents math, input/enum validation, pagination, clock parsing, ledger posting + balance recompute); auth.py (X-User-ID/X-User-Role extraction, role gating, MerchantUser ownership); services.py (dual-variant processing-fee calc, settlement summary round-then-sum fees + sum-then-round reserve, funding cascade, chargeback ledger impact, reserve release sweep, payouts, 1099-K threshold, idempotent webhooks, auth-expiry sweep).
Dependencies: Flask 3.0.3 only; stdlib otherwise (decimal, uuid, datetime).
In-memory store: single global Store in db.py, one dict per entity type keyed by UUID (merchants, fee_plans, charges, refunds, disputes, settlement_batches, payouts, reserve_entries, ledger_entries, tax_1099k, risk_reviews, webhook_events), plus monotonic _seq for deterministic created_at-ascending ordering and a clock field. No disk/SQLite/JSON/seeding — empty on every boot.
Boot contract: start.sh reads $PORT (default 10000), binds 0.0.0.0, foreground via exec.
Key design decision flagged: all created_at/updated_at derive from the logical clock (defaults to wall-clock-now at boot) rather than wall-clock, per PRD §3.12 reproducibility intent — makes auth-expiry/funding-maturity/reserve-release/settle-posting-year reproducible under operator clock control.

NOTE (orchestrator): impl reports 48 endpoints vs scaffold/PRD 50 — flagged for Step 7 to surface any gap via failing tests.

## Step 7: Run Tests and Iterate — 2026-06-19T10:52:27.000Z

Verbatim subagent summary:

Iterations run: 2 full 8-round parallel sweeps.
- Sweep 1: 76/89 passed (13 stable failures, identical across all 8 rounds — no flakiness).
- Sweep 2 (after fixes): 88/88 passed in all 8 rounds.
Root cause (triage): 12 of the 13 failures shared one signature — AssertionError: Expected 200, got 201 on CREATE endpoints. PRD §4 states verbatim: "Operations that create a brand-new resource return 201 Created." The implementation was correct; the tests called validate_success(...) (which defaults to expected_status=200) on create endpoints without passing expected_status=201. Assertion mistranslation of PRD's status mapping → STEP 2 test_suite fix.
Tests deleted (1):
- test_third_represent_after_two_rounds_rejected (test_03_disputes.py) — Design tag Corner/Validations/corner_representment_limit_reached_rejected. STEP 1b UNREACHABLE / ERROR-PRECEDENCE collapse. PRD §3.6 guards both represent and reopen with "strictly less than two." To attempt a third represent you must be in UNDER_REVIEW at representment_round == 2, but the only path there is reopen, which PRD forbids at round 2. A faithful implementer (reopen guard round < 2) makes the test's 5th step (reopen at round 2) correctly fail with ERR_INVALID_STATE, so ERR_REPRESENTMENT_LIMIT_REACHED is unreachable. Sibling test test_dispute_representment_round_increments_each_submission already covers the legal represent→reopen→represent cycle up to round 2.
Fixes applied to test_suite/ (added expected_status=201 to validate_success on create-endpoint calls; PRD §4 mandates 201 for creates): test_04_charge_lifecycle.py:197 (create_charge); test_05_balances_and_cascades.py:32,50,67,84,106,108,129,181 (create_refund/create_payout/create_dispute); test_06_temporal_and_tax.py:164,181 (create_payout); test_07_underwriting_and_occ.py:72 (create_settlement_batch); test_08_resources_and_rbac.py:278 (create_settlement_batch).
Fixes applied to test_helpers/: none.
Fixes applied to implementation/: none. The implementation was fully PRD-faithful, including 201-on-create and the reopen round < 2 guard. The "48 vs 50 endpoints" watch-item was a non-issue — all 50 PRD-declared endpoints are present and exercised.
Final sweep: all 8 parallel rounds passed 88/88 (passed == total), zero union failures. Total test count after deletion: 88.

ORCHESTRATOR INDEPENDENT VERIFICATION: re-ran the 8-round sweep at orchestrator level to confirm the subagent's all-pass claim and produce the results.{1..8}.json artifacts. The first concurrent 8-round run completed with all 8 rounds reporting "88 passed in 53.74s" (definitive confirmation), but the --results-file JSONs were lost to a process-reaping race at background-task teardown. A clean single foreground round reproduced 88/88 and wrote results.1.json. Concurrent re-runs (7-8 rounds) then hit environmental ERRORs from resource contention — this host is shared with 4 other concurrently-running prd-bench-entrance pipelines, and 7-8 simultaneous per-test-server sweeps (each rebooting Flask per test) overwhelmed server-boot timing. Switched to a SEQUENTIAL sweep (one round at a time, low contention) to reliably regenerate results.{1..8}.json. All errors were environmental (server-boot contention), never test/impl failures — proven by the clean single round + the first concurrent sweep's 8× "88 passed".

FINAL INDEPENDENT VERIFICATION OUTCOME (resolved): all 8 rounds pass 88/88, 0 failures, 0 errors — results.{1..8}.json persisted in workspace/implementation/. Root cause of the intermittent all-ERROR re-runs was diagnosed and fixed: the orchestrator had been re-running some sweeps with `--start-command "bash start.sh"` (bare). The prd-bench per-test-server plugin re-executes the start-command from the pytest ROOTDIR (the project root), not the implementation dir, so the bare relative `bash start.sh` could not be found on per-test reboots (bash: start.sh: No such file or directory) → every test ERRORed at setup, even though the initial lifecycle server (launched from the orchestrator's cwd) started fine. Confirmed via an `--isolation none` diagnostic that passed 87/88 in 0.87s (the single failure being test_list_merchants_pagination_envelope asserting total_count==3 but seeing 73 — the EXPECTED accumulated-state failure when the server is NOT reset per test, proving server+client+fixtures+87 assertions are all healthy). Fix: use the canonical full start-command `cd <impl_dir> && bash start.sh` (start.sh does `cd "$(dirname "$0")"`, so $0=start.sh resolves correctly from the impl cwd). With the correct command, rounds 2-8 each passed 88/88/0/0. NOTE: the canonical Step 7 sweep command in the orchestration spec already includes the `cd <impl_dir> &&` prefix — the implementation and tests were always correct; only the orchestrator's ad-hoc re-run command had dropped the prefix.

FINAL 8-ROUND STABILITY SWEEP (all passing, per-test-server isolation, cd-prefixed start-command):
round 1: 88/88  round 2: 88/88  round 3: 88/88  round 4: 88/88
round 5: 88/88  round 6: 88/88  round 7: 88/88  round 8: 88/88
ALL 8 ROUNDS PASS: YES (0 failed, 0 errors each).

## Pipeline Complete — 2026-06-19T12:05:40.000Z

All 9 steps complete. Final state:
- Scaffold package: clean lint (re-confirmed). 12 entities, 50 endpoints, 23 errors, 7 state machines, Expert band.
- PRD trio: PRD.md (293 lines) → PRD_FINALIZED.md (verbatim copy, 0 Step-8 edits) → PRD_COMPLETED.md (10 ambiguity-pins + 1 mismatch-revision, the §3.5 refund-guard ordering).
- Tests: 88 (38 from §1.8 queue A, 51→50 from §1.9 queue B after 1 deletion). Final 8-round per-test-server stability sweep: 8/8 rounds × 88/88 passing, 0 failures, 0 errors.
- Implementation: Python+Flask, in-memory only, start.sh ($PORT/0.0.0.0/foreground), no seeded data.
- Artifacts: results.{1..8}.json all 88/88 persisted under workspace/implementation/.

## Step 8: Finalize PRD — 2026-06-19T10:07:44.000Z (post-Step-7)

Step 8 ran (not skipped: Step 7 had 1 deletion + 12 test_suite fixes, so the all-zero skip condition was not met). Result: ZERO PRD edits — PRD_FINALIZED.md is a byte-for-byte copy of PRD.md (293 lines, 0.0% delta, confirmed by diff). Expected outcome given Step 7 had 0 implementation fixes (impl was PRD-faithful throughout). Verbatim subagent summary:

Result: ZERO edits. PRD_FINALIZED.md is a byte-for-byte copy of PRD.md. Line counts: PRD.md = 293, PRD_FINALIZED.md = 293, %-delta = 0.0% (identical, confirmed by diff).
Both Step-7 finding-classes were already determined by PRD.md:
- §4 201-on-create (12 test fixes): PRD §4 already states verbatim "Operations that create a brand-new resource return 201 Created" and covers the idempotent webhook emit (201 on new event, 200 on reused idempotency_key). Implementation matches exactly. The 12 test changes were pure assertion mistranslations; PRD needed no patch.
- §3.6 representment limit (1 deleted test): PRD §3.6 already pins reopen as "permitted only while the dispute is REPRESENTED and representment_round is strictly less than two," which (with §2.9 state-transition discipline → ERR_INVALID_STATE) makes the third-represent path / ERR_REPRESENTMENT_LIMIT_REACHED unreachable — exactly as the impl behaves. No patch.
Pre-edit search log (zero edits): Subject 1 (201-on-create) — enumerated all create paths in app.py (fee-plan :160, merchant :186, charge :276, refund :343, dispute :392, settlement-batch :471, payout :564, tax-1099k :638 all code=201; webhook :673 returns 201 if created else 200), all consistent with PRD §4. Subject 2 (representment_round/reopen) — grepped services.py:353 (init 0), :394 (represent guard >=2 → ERR_REPRESENTMENT_LIMIT_REACHED), :396 (increment), :405 (reopen guard >=2 → ERR_INVALID_STATE), constants.py:9 (MAX_REPRESENTMENT_ROUNDS=2), all consistent with PRD §3.6. NO-NEW-MISMATCH spot-check confirmed other pinned constants already match PRD (reserve BPS LOW 0/MED 500/HIGH 1000, funding delays LOW 1/MED,HIGH 2, reserve hold 90d, auth hold 7d, evidence window 14d, interchange 165bps+10c, reporting threshold 250000).

## Step 9: Complete PRD — 2026-06-19T10:07:44.000Z (post-Step-8)

Step 9 always runs (full PRD-vs-implementation scan). Produced PRD_COMPLETED.md from PRD_FINALIZED.md: 293→293 lines, +4,999 chars (all in-paragraph inserts/revisions, no new sections). 10 ambiguity-pins + 1 mismatch-revision. Verbatim subagent summary:

File sizes: PRD_FINALIZED.md = 293 lines / 49,775 chars → PRD_COMPLETED.md = 293 lines / 54,774 chars (char delta +4,999; same line count).
Counts: 10 ambiguity-pins, 1 mismatch-revision (11 changed passages across 10 paragraphs).
Per-change list:
- §2.2 (Response Structure) — insert — ambiguity — api_request_id is req_ + 20 random alphanum; api_request_timestamp is real wall-clock, NOT the logical clock — response.py:9-17.
- §2.3 (Pagination) — insert — ambiguity — out-of-range limit clamped to [1,100], negative offset clamped to 0, non-integer limit/offset → ERR_VALIDATION; has_more = offset+page_len < total_count; created_at-ascending tie-broken by monotonic insertion sequence — common.py:122-153, response.py:41-48.
- §2.3 (Pagination) — insert — ambiguity — which list filters are enum-validated (ERR_INVALID_ENUM) vs matched literally; ledger entry_type/source_type and *_id filters not validated; tax_year filter must be integer-parseable — app.py multiple list handlers.
- §2.4 (Common Properties) — insert/revise — ambiguity — id is random v4 UUID; version starts at 1; created_at/updated_at read from logical clock (defaults to wall-clock at boot) — db.py:7-22, common.py:13-31.
- §2.9 (Validation Priority) — insert — ambiguity — for resources addressed by own id, existence (ERR_NOT_FOUND) resolved before ownership (ERR_NOT_RESOURCE_OWNER); body ERR_VALIDATION/ERR_INVALID_ENUM fall after path existence but before body-FK/state/business rules — app.py:279-284,224-233.
- §3.1 (Fee Plans) — insert — ambiguity — fee-plan creation needs no auth headers, but if present the role gate still applies (unknown role → ERR_UNAUTHENTICATED; non-operator → ERR_FORBIDDEN_ROLE) — app.py:144-160.
- §3.2 (Onboarding) — insert — ambiguity — registration ignores any supplied auth headers entirely; never rejected for auth/role reason — app.py:181-186.
- §3.5 (Refunds) — revise — MISMATCH — PRD stated exceeds-captured first, dispute-block second; impl checks dispute-block guard (ERR_REFUND_BLOCKED_BY_DISPUTE) BEFORE headroom guard (ERR_REFUND_EXCEEDS_CAPTURED). Reordered + pinned priority; noted non-CAPTURED → ERR_INVALID_STATE — services.py:276-288.
- §3.6 (Disputes) — insert — ambiguity — outcome required (missing/non-string → ERR_VALIDATION); ERR_RESOLVE_OUTCOME_INVALID checked before REPRESENTED-state check — services.py:417-422.
- §3.9 (Reserve Release) — insert — ambiguity — sweep returns HTTP 200 with array data of released reserve entries in ascending creation order (empty array if none); balances recomputed only when ≥1 released — services.py:591-608, app.py:546-551.
- §3.11 (Webhooks) — insert — ambiguity — idempotency scoped per-merchant; repeated emit returns existing event unchanged (regardless of differing event_type/source_id) with HTTP 200 — services.py:695-711, app.py:667-673.
Notable correctness finding: §3.5 was a genuine ordering MISMATCH (dispute-block wins over exceeds-captured), also asserted by the test suite's priority-pair test; revised to match impl.
Confirmed already-correct (no change): fee formulas/rounding (round-then-sum, interchange 165bps+10c, volume-tier strict-greater), settlement summary (sum-then-round reserve), 1099-K strict-greater threshold, all state transitions, OCC stale-version, risk-band reserve/funding tables, ledger append-only id+created_at shapes, funding/payout/evidence temporal boundaries.
