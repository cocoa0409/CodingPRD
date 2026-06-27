# Worklog — task_0512_tax_prep_refund_advance

## Step 1: Create task directory — 2026-06-27T03:35:00.000Z

Created `tasks/task_0512_tax_prep_refund_advance/` and `tasks/task_0512_tax_prep_refund_advance/workspace/`. Pre-allocated directory name used as instructed (no re-scan of indices). Difficulty target: Expert (§0.4, 10–15 entities).

## Step 2: Generate scaffold — 2026-06-27T03:58:00.000Z

All three artifacts written and pass `scaffold_lint.py` cleanly.

**Complexity profile**: Primary archetype workflow_orchestration + secondary ledger_reconciliation; hybrid topology; branching/cyclic state machines; peer_roles; immediate consistency. Layers: cascading_side_effects, dual_variant_calculation, rate_threshold_triggers, optimistic_concurrency.

**Entities (13)**: Office, ComplianceCredential, Preparer, Client, Appointment, TaxReturn, DocumentIntake, FeeLine, AuditProtection, EfileSubmission, RefundTransfer, RefundAdvance, ComplianceClock. 47 endpoints, 26 errors, 15 validations, 4 roles (OfficeManager, FrontDeskAgent, TaxPreparer [entity_backed:Preparer], BankProductOfficer).

**State machines (5)**: TaxReturn (8-state, cyclic e-file reject→correct loop + branching ACK/reject + cancellation cascades), Appointment, RefundAdvance (branching approve/deny), RefundTransfer (PENDING_FUNDING self-loop `/adjust` + disburse + cancel), AuditProtection. One concurrency rule: OCC supersede on `POST /refund-transfers/{id}/disburse` via `/adjust`-bumped version (true race, 412).

**Key calculations (4)**: `prep_fee_total` (tiered band multiplier, round-per-line, returning-client discount min(cap,%)); `advance_max_eligible` (nested min over refund-tier cap × risk-band fraction); `refund_disbursement_waterfall` (ordered fee-deduction buckets, net floored at 0, shortfall); `disbursement_surcharge` (2.9% round-per-bucket-then-sum — pinned order, diverges from sum-then-round 610 vs 609). All test asserts use literals computed against the formulas.

**Difficulty design (§1.8)**: 9 rules × 2 = 18 instances. **Corner design (§1.9)**: 38 active instances across 12 sections + 6 `excluded_because` stubs. Lint clean: 523 calls scanned, all 13 entities' FKs reverse-reachable, 26 errors triggerable, 62 unique instance names. `api_prefix=""` (flat paths), all path ids normalized to `{id}`. Clock default `2026-05-01T00:00:00Z`.

## Step 3: Copy INSTRUCTION.md — 2026-06-27T04:00:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0512_tax_prep_refund_advance/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-06-27T04:04:00.000Z

Generated `workspace/PRD.md` (283 lines, ~6,170 words) from the scaffold. Both design files withheld.

**Structure:** 5 top-level sections. §1 Introduction. §2 (9 subsections: Access Control, Response Structure, Pagination, Common Resource Properties, Nested Retrieval & Validation Ordering, OCC, Money/Precision/Rounding, EFIN/PTIN compliance gates, Hierarchical Consistency/Counters/Cascades). §3 (9 workflow subsections by lifecycle). §4 endpoint table (all 47 endpoints). §5 error table (all 26 errors).

**Coverage:** All 11 entities + ComplianceClock singleton covered (`common_fields: false` for clock called out). All 5 state machines narrated (Appointment, TaxReturn incl. EFILED_REJECTED→PREPARED loop + 4 cancellation sources, RefundAdvance, RefundTransfer incl. self-loop adjust/version-bump, AuditProtection). All 4 calculations in precise prose with pinned eval order + constants (prep_fee_total, advance_max_eligible nested-min, refund_disbursement_waterfall 4-bucket, 2.9% disbursement_surcharge round-per-bucket-then-sum). All 15 validations as fixed precedence chain. Single OCC rule on refund-transfer disburse fully expressed (expected_refundtransfer_version → ERR_STALE_VERSION/412). Cross-entity cascades stated.

**Hard Contracts:** Contract 1 (field-name coverage 51/51 entity fields, 41/41 params) PASS; Contract 2 (rule coverage 15/15 validations, 1/1 OCC, all 5 SM transitions, 4/4 calcs, sibling-branch symmetry) PASS; Contract 3 (§3 path purity, 401 backtick tokens, 0 paths/methods) PASS.

## Step 5: Generate unit tests — 2026-06-27T04:07:00.000Z

Generated `test_helpers/` (9 files) + `test_suite/` (conftest + 10 test files). **74 tests total**: **36 Queue A (Difficulty)** + **38 Queue B (Corner)**.

- All 74 docstrings carry exactly one verbatim `Design:` tag; all resolve to real instances (no dual/untagged/dangling). All 94 PRD citations verbatim-match PRD.md. No skip/skipif/xfail; no scaffold leakage.
- **Queue A:** 17 of 18 difficulty instances covered ≥2 tests each. **Queue B:** all 38 non-stub corner instances covered ≥1 test each. 6 `excluded_because` stubs verified (not translated).
- All numeric literals independently re-derived from PRD formulas (prep-fee 40800/38300/72750/21600, advance caps 50000/150000, surcharge 610 vs 609, waterfall net 28985/421005, shortfall 4795, repaid 1020/60000).

**Instances skipped (1):** `Difficulty/priority_pair_validation_conflict/credential_safety_vs_amend_referential_on_efile` — SKIPPED on unique-derivability. PRD does not commit to ordering between credential (priority 8) and amend-target (priority 9) same-category business rules; §2.5 tiebreak applies only to the common precedence list, not these two. Either `ERR_CREDENTIAL_INVALID` or `ERR_AMEND_TARGET_NOT_ACCEPTED` is PRD-faithful. Sibling `state_vs_efin_suspended_on_efile` kept (state check sits in §2.5 common precedence).

## Step 6: Generate implementation — 2026-06-27T04:07:00.000Z

Generated Python + Flask in-memory implementation in `workspace/implementation/`.

**Files:** start.sh (foreground, reads $PORT, binds 0.0.0.0, `exec python3 app.py`), requirements.txt, app.py, db.py (logical clock default `2026-05-01T00:00:00Z`), errors.py (26 errors), response.py (fixed envelope), middleware.py (auth 4 roles), money.py (Decimal half-up), timeutil.py, constants.py, models.py (12 entities), routes/ (13 modules), services/ (calculations, returns SM, counters).

**Endpoints:** 47 — matches scaffold/PRD table exactly.

**State machines:** TaxReturn (8-state incl. EFILED_REJECTED→PREPARED loop, locked after reject_count>3, 4-source cancel cascade); Appointment (clock-gated CHECKED_IN/NO_SHOW); RefundTransfer (PENDING_FUNDING self-loop /adjust version bump, OCC /disburse, /cancel); RefundAdvance (REQUESTED→APPROVED/DENIED→DISBURSED→REPAID via transfer-disburse bubble); AuditProtection (ACTIVE→CANCELLED, auto-VOIDED on return cancel).

**Calculations (Decimal half-up, pinned order):** prep_fee_total (band multiplier, round-per-line, capped returning-client discount as negative FeeLine); advance_max_eligible (nested min, HIGH risk→0); refund_disbursement_waterfall (4 ordered buckets, net + shortfall); disbursement_surcharge (2.9% round-per-bucket-then-sum). Counters recomputed from authoritative state. Validation precedence follows PRD §2.5.

## Step 7: Run tests and iterate — 2026-06-27T04:32:00.000Z

Final state: **all 8 parallel rounds clean, 74/74 tests passing each round, 0 failures, 0 errors.** (Orchestrator re-ran the full 8-round sweep to regenerate `results.{1..8}.json` artifacts after the subagent's run — all 8 confirmed 74/74.)

**Iterations run:** 2 (1 baseline diagnostic sweep + 1 verification sweep).

**Tests deleted:** None. (The one genuinely-failing test was split per STEP 1c rather than deleted, since its core assertion was PRD-covered.)

**Fixes applied to test_suite/:**
- `test_01_fee_and_advance_calculations.py :: test_disbursement_surcharge_round_per_bucket_then_sum` — Assertion read `disbursed["surcharge_cents"]`, but PRD §3.7 only states "the disburse response reports an electronic-disbursement surcharge" and pins the round-per-bucket *value* (610), never the response field NAME (COMPUTED-FIELD SILENCE on field name; other fields `net_to_taxpayer_cents`/`fee_shortfall_cents` are named verbatim). Per STEP 1c partial-coverage handling: kept the PRD-covered/uniquely-derivable value assertion (`== 610`, discriminates round-per-bucket from sum-then-round=609), dropped the unpinned-key constraint by accepting either PRD-faithful spelling (`surcharge_cents` or `disbursement_surcharge_cents`).

**Fixes applied to implementation/:**
- `start.sh` — The two `ERROR` results were "API server could not be restarted" flakiness, not logic bugs. Root cause: `start.sh` spawned a separate `python3 -c "import flask"` probe interpreter on every per-test reboot (74 reboots × 8 concurrent rounds); under 8× CPU load that extra spawn could push boot past the runner's restart window. Replaced the per-boot probe with a one-time `.deps_ok` marker (build-artifact flag, no application/entity state — does not violate in-memory rule), then `exec python3 app.py` directly. Solo wall time 76s → 45s; all 8 concurrent rounds now boot reliably with zero restart errors.

**Key finding:** No implementation business-logic changes needed — surcharge value was already computed correctly (610). Only real defects: a test pinning an unpinned response-field name, and a boot-latency race in `start.sh` under 8× parallel load.

## Step 8: Finalize PRD — 2026-06-27T04:33:00.000Z

Produced `workspace/PRD_FINALIZED.md`. PRD.md = 283 lines, PRD_FINALIZED.md = 283 lines (one line revised in place, 0% line delta).

**Changes (1):**
- §3.7 — revise — pinned the disburse-response surcharge field name to `disbursement_surcharge_cents` (PRD originally named the surcharge only in prose, leaving the response key underdetermined) — `implementation/routes/refund_transfers.py:143`.

**Pre-edit search log:** Subject = name of disburse-response surcharge field. Enumerated `routes/refund_transfers.py:141-144` (only place surcharge reaches a response; internal `surcharge_cents` renamed to `disbursement_surcharge_cents` at boundary), `services/calculations.py:93-107` (value already correct, algorithm pinned), `models.py:80-81 refund_transfer_dict` (surcharge not persisted, absent on get/list/adjust/cancel), grep confirmed no other endpoint emits it. Wording scoped to "a `disbursement_surcharge_cents` field on the disburse response body" (not persisted/transfer-wide) to stay consistent with get/list/adjust/cancel paths.

**No PRD edit:** start.sh fix (pure build/launch-latency, no behavioral content); test-suite fix confirmed exactly the §3.7 field-name silence patched.

## Step 9: Complete PRD — 2026-06-27T05:12:00.000Z

Produced `workspace/PRD_COMPLETED.md` (full PRD-vs-implementation scan). PRD_FINALIZED.md (283 lines, 43,977 chars) → PRD_COMPLETED.md (283 lines, 46,341 chars; +2,364 chars; all edits in-paragraph, 0 line-count change). **9 ambiguity-pins, 0 mismatch-revisions.**

(Note: the Step 9 subagent hit a transient API 503 mid-scan after applying its first 6 edits; orchestrator resumed it via SendMessage with context intact, and it completed the exhaustive walk + emitted the summary. Final diff = exactly 9 changed lines, no new sections, no removed content.)

**Changes (9):**
- §2.3 Pagination — insert — ambiguity — out-of-range `limit`/`offset` clamp (limit→[1,100], offset→≥0), non-integer/empty → default, equal `created_at` ties break by creation order (stable) — `routes/common.py:30-45,48-53`.
- §2.4 Common Resource Properties — insert — ambiguity — `created_at`/`updated_at` from logical clock (not wall-clock), `version` begins at 1, client-supplied server-managed fields ignored — `db.py:50-52`, `models.py:16-23,21`, `routes/returns.py:75`.
- §3.3 Open Return — revise — ambiguity — `prep_fee_cents` "unset" means present-but-null — `models.py:174`.
- §3.4 Assignment — insert — ambiguity — reassignment allowed from any state, capacity check uses resulting count without double-counting already-assigned return or counting closed returns, counters recompute (+1 new / −1 prior) — `routes/returns.py:128-147`, `services/counters.py:26-37`.
- §3.6 Audit-Protection cancel — insert — ambiguity — cancel defined only from `ACTIVE` (else `ERR_INVALID_STATE`), checked before return-accepted rule — `routes/audit_protections.py:64-70`.
- §3.7 Refund-Transfer create — insert — ambiguity — `disbursed_refund_cents`/`net_to_taxpayer_cents`/`fee_shortfall_cents` present-but-null until disbursed — `models.py:235-239`.
- §3.7 Refund-Transfer adjust — insert — ambiguity — adjust defined only from `PENDING_FUNDING` (→ `ERR_INVALID_STATE`), checked before figure validation — `routes/refund_transfers.py:66-72`.
- §3.8 Refund-Advance request — revise — ambiguity — `approved_cents` "unset" means present-but-null — `models.py:249`.
- §3.8 Underwrite — insert — ambiguity — `decision` literals `APPROVE`/`DENY` (else `ERR_INVALID_REQUEST`), underwrite defined only from `REQUESTED` (→ `ERR_INVALID_STATE`) before business rules, `ERR_BANK_PRODUCT_DISABLED` before eligibility — `routes/refund_advances.py:71-94`.

**Verified already-pinned (no change):** disburse waterfall ordering/net-floor + `fee_shortfall_cents`; disburse business-rule order; `disbursement_surcharge_cents` field + response-only placement; STALE_VERSION precedence (§2.5); credential expiry strictly-after; ComplianceClock response shape; generic `ERR_INVALID_STATE` for transition/efile/ack/disburse/cancel (covered by §2.5 — only adjust, absent from that list, needed a pin).
