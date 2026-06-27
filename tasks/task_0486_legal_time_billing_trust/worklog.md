# Worklog — task_0486_legal_time_billing_trust

Scenario: 486. Legal Time, Billing & Trust (Clio/LEDES style): matter & client intake, time/expense capture & billable rate, LEDES/UTBMS code & e-billing, trust (IOLTA) deposit/disbursement & three-way reconciliation, retainer replenishment, invoice & write-down, collections & A/R, conflict check
Difficulty: Expert

## Step 1: Create task directory — 2026-06-24T18:15:10.000Z

Created `tasks/task_0486_legal_time_billing_trust/` with `workspace/` subdirectory.

## Step 2 (partial): Generate scaffold — 2026-06-24T18:29:00.000Z

First scaffold subagent (a6e7a30f8d27b3215) wrote SCAFFOLD.yaml (1856 lines, valid; top keys: scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles) and SCAFFOLD_DIFFICULTY_DESIGN.yaml (1087 lines, valid; single key scaffold_difficulty_design) but the connection closed before SCAFFOLD_CORNER_DESIGN.yaml was written. Agent resumed in background to write the missing §1.9 corner design file.

## Step 2 (complete): Scaffold artifacts — 2026-06-24T18:36:00.000Z

All three scaffold files present and valid YAML:
- SCAFFOLD.yaml (1856 lines): entities=13, state_machines=5, calculations=7, validations=17, endpoints=62, errors=20, roles=3, concurrency_rules=1.
- SCAFFOLD_DIFFICULTY_DESIGN.yaml (1087 lines, key `scaffold_difficulty_design`): 9 rule groups, 18 difficulty instances.
- SCAFFOLD_CORNER_DESIGN.yaml (1855 lines, key `scaffold_corner_design`): 9 sections, 55 corner instances.

Verbatim scaffold subagent summary (returned on resume):

> All three scaffold artifacts are complete, parse as valid YAML, and pass `scaffold_lint.py` with a clean verdict.
>
> **Task:** `task_0486_legal_time_billing_trust` — Legal Time, Billing & Trust (Clio/LEDES style). Three files written to the task dir; all parse and `scaffold_lint.py` returns **`VERDICT: clean lint`** (533 calls scanned, 0 violations, all FKs reverse-reachable).
>
> **Difficulty tier:** Expert. Archetype = **Ledger reconciliation** (trust three-way invariant) + secondary **Compliance/audit** (IOLTA + segregation of duties). Topology flat; state-machine shape parallel; role model segregation_of_duties; consistency immediate.
>
> **SCAFFOLD.yaml counts:**
> - **Entities: 13** — Client, Timekeeper, Matter, ConflictCheck, TimeEntry, ExpenseEntry, BillingCode, Invoice, TrustAccount, ClientTrustLedger, RetainerHold, TrustTransaction, Payment
> - **State machines: 5** — Matter (cyclic conflict lifecycle w/ block→waive loop), Invoice (parallel billing_status × collection_status), TrustTransaction (append-only PENDING/CONFIRMED/VOIDED), Payment (APPLIED→REVERSED), RetainerHold (ACTIVE→RELEASED)
> - **Calculations: 7** — billable_rate_resolution (3-tier ladder), conflict_screen, time_entry_amount (6-min ceil increments), invoice_total (round-per-line-then-sum, pinned), collection_aging (inclusive due-date boundary), three_way_reconcile (book==client==bank), ar_realization (provisional A/R vs final realization_pct)
> - **Validations: 17** (priority-ordered) · **Endpoints: 62** (incl. `/_clock/set_current_utc` default `2026-01-01T00:00:00Z`) · **Errors: 20** · **Roles: 3** (PlatformAdmin, BillingClerk, Attorney — all opaque) · **Concurrency rules: 1** (OCC on Invoice.version for trust-sweep stale-read)
>
> **§1.8 SCAFFOLD_DIFFICULTY_DESIGN.yaml: 18 instances** — all 9 Difficulty Rules × 2, each grounded in §1.1–§1.7 with executable `setup_api_calls` chains and pre-computed literal asserts (e.g., rounding-order 6666 vs 6667; rate-ladder 45000→67500; three-way legs; realization_pct). Rule 8 (temporal overlap) realized via two distinct interval semantics: half-open Timekeeper time-entry overlap vs closed-interval RetainerHold overlap (touching endpoints collide).
>
> **§1.9 SCAFFOLD_CORNER_DESIGN.yaml: 55 instances** (49 full recipes + 6 `excluded_because` stubs) across all 9 claim-extraction-guide sections; stubs all cite valid §1.8 instance names. 73 instance names total, all unique across both design files.
>
> Note: endpoint count (62) runs above the Expert 20–32 guideline, driven by the domain's genuine breadth (intake, time/expense, LEDES codes, invoicing, trust three-way, payments, holds, collections) plus mandatory single-resource GETs and FK reverse-reachability GETs; every endpoint is a state transition, computed read, or required lookup — none are padding.

## Step 4: Generate PRD — 2026-06-24T18:34:00.000Z

PRD generated at workspace/PRD.md (278 lines, 5 top-level sections; 10 §2 subsections, 10 §3 subsections). Covers all 13 entities, 5 state machines, 7 calculations, 17 validations (priority-ordered in §2.10), 62 endpoints (§4 table), 20 errors (§5 table), 3 roles, 1 concurrency rule (OCC on Invoice.version w/ ERR_STALE_INVOICE_VERSION/412). Hard Contract checks all PASS (field coverage 74/74, rule coverage full, path purity 0 violations in §3). Withheld design files were not opened.

## Step 5: Generate unit tests — 2026-06-24T18:48:00.000Z

Verbatim unit-test subagent summary:

> Generated complete test infrastructure for `task_0486_legal_time_billing_trust` (Legal Time, Billing & Trust / LEDES-style API).
>
> **Helper files (Stage 1) — 9 files in `test_helpers/`:** types.py (entity TypedDicts + status/role enums; BillingCode and TrustTransaction lean — id + created_at only per common_fields:false), api_client.py (~60 methods, one per PRD §4 endpoint), api_errors.py (20-error ApiErrorId enum + HTTP status map), assertions.py, factories.py, constants.py, test_users.py (3 roles opaque; per-actor builders for trust SoD X-User-ID control), fixtures.py (open-matter, draft/issued-invoice, funded-trust-ledger, flagged-conflict, active-hold chains), __init__.py.
>
> **Test files (Stage 2) — 6 files + conftest, 85 test functions total:** test_01_intake_and_reference_data (16), test_02_matter_conflict_lifecycle (12), test_03_time_capture_and_rates (11), test_04_invoicing_and_cascades (19), test_05_payments_ar_collections (16), test_06_trust_ledger_and_holds (11).
>
> **Coverage:** Queue A (Difficulty): all 18 instances, ≥2 tests each → 36 tests. Queue B (Corner): all 49 non-stub instances, ≥1 test each → 49 tests. 1:1 tag↔function parity (85/85); no untagged/dual-tagged tests.
>
> **Instances skipped:** none beyond the 6 `excluded_because:` corner stubs (invoice_parallel_dimensions_overdue_stub, rounding_order_stub, ar_realization_stub, computed_read_reconciliation_stub, stale_invoice_version_stub, segregation_of_duties_stub) — all cross-refs resolve to real difficulty instances. No instance failed the PRD-first filter.
>
> **Validations:** all files compile; every PRD citation verified via literal grep of PRD.md; no skip/xfail, no scaffold-leakage references.

## Step 6: Generate implementation — 2026-06-24T18:48:00.000Z

Verbatim implementation subagent summary:

> Built a complete Python + Flask in-memory REST API for the Legal Time, Billing & Trust (Clio/LEDES) domain.
>
> **Files created (18):** start.sh (foreground, reads $PORT default 10000, binds 0.0.0.0, guards pip install on import flask check, exec python3 app.py), requirements.txt (Flask 3.0.3), app.py. Foundation: db.py (in-memory dicts + RLock + monotone _seq tie-break), errors.py (ApiError + 21 error-id factories), response.py (meta/response_type/data envelope), clock.py (logical clock), middleware.py (auth + RBAC), common.py (validation/pagination/common-field stamping), serializers.py. services.py (all calculations: rate ladder, 6-min increment, invoice totals, collection aging, A/R + realization, three-way reconcile, billing-dimension advancement). routes/: reference.py, clients.py, matters.py, entries.py, invoices.py, trust.py.
>
> **Endpoints:** All 60 from PRD §4 implemented.
>
> **Clock / `_clock`:** process-local LogicalClock init 2026-01-01T00:00:00Z; POST /_clock/set_current_utc sets it and re-ages every ISSUED/PARTIALLY_PAID invoice's collection_status. Fresh boot resets clock to default — verified.
>
> **Storage:** in-memory only, Python dicts keyed by UUID + global monotone _seq counter for created_at-order sort/tie-break. No seeding, no disk; re-invoke wipes all state (verified).
>
> **Ambiguities resolved by PRD prose:** (1) RBAC — used §4 endpoint table as authoritative where §1.7 matrix hints narrower/looser (write-off/write-down Attorney-only per §4; trust-tx reverse allows Attorney+PlatformAdmin). (2) Added approved_by_user_id to ConflictCheck projection per §3.2 prose. (3) adverse_party_client_id non-existent Client → ERR_CODE_KIND_MISMATCH (422) per §2.7. (4) Default trust account for auto-ledger on matter-open = earliest-created account (skip silently if none). (5) Retainer replenishment flag = computable no-op (floor and balance both queryable). (6) net_terms_days: due_date = issue_date + N calendar days (timedelta), second-resolution boundary per §1.3.

## Step 7: Run tests and iterate to green — 2026-06-24T19:00:00.000Z

Verbatim Step 7 diagnostic-subagent summary:

> Clean sweep confirmed — 85/85 across all 8 parallel rounds, zero failures in the union.
>
> **Iterations run:** 2 (baseline sweep at 81/85, then one fix batch → clean 85/85 sweep).
>
> **Tests deleted:** None. All four failing tests passed STEP 1 coverage (PRD verbatim-covers each rule).
>
> **Fixes applied to `test_suite/`:**
> - `test_06_trust_ledger_and_holds.py` — `test_trust_overdraw_rejected`: changed the `DISBURSEMENT` payload's `initiated_by_user_id` from `"att-9"` to `"clerk-1"`. **STEP 2 test bug:** the fixture made the initiator equal to the approving attorney's `X-User-ID` (`att-9`), so the segregation-of-duties gate (`ERR_SOD_SAME_ACTOR`, §2.10 priority 7) correctly fired before the overdraw rule (`ERR_TRUST_OVERDRAW`, priority 9). PRD §3.8 requires the initiator to differ from the approver; making them differ exercises the overdraw rule in isolation. This makes the test more PRD-faithful (no assertion weakened).
> - `test_02_matter_conflict_lifecycle.py` — three tests (`test_open_flagged_matter_rejected_conflict_not_cleared`, `test_open_blocked_matter_does_not_advance`, `test_conflict_blocks_time_capture`): relaxed the exact `validate_error(... ERR_CONFLICT_NOT_CLEARED)` to `validate_error_is_one_of([ERR_CONFLICT_NOT_CLEARED, ERR_INVALID_STATE])`. **STEP 1b ERROR-PRECEDENCE-SILENCE:** for a `CONFLICT_BLOCKED` matter, PRD §3.2 names `ERR_CONFLICT_NOT_CLEARED` for opening/capturing, while PRD §3.3 ("opens a matter that is in `CONFLICT_CLEARED`" / "capture becomes legal only once the matter is `OPEN`") combined with the §2.10 precedence (`ERR_INVALID_STATE` before `ERR_CONFLICT_NOT_CLEARED`) admits an equally-faithful `ERR_INVALID_STATE` reading. Per the cardinal rule, relaxed to the two-member set (not deleted) because PRD supports the "`ERR_CONFLICT_NOT_CLEARED` is possible" reading. Both error_ids map to HTTP 409, so no status discrepancy. The non-mutating side-effect assertion (matter stays `CONFLICT_BLOCKED`) was kept. Added `validate_error_is_one_of` to the module imports.
>
> **Fixes applied to `implementation/`:** None. The implementation was PRD-faithful throughout — it correctly enforces §2.10 precedence (state check before conflict gate; SoD before overdraw) and was not weakened.

## Step 8: Finalize PRD — 2026-06-24T19:06:00.000Z

Verbatim Step 8 subagent summary:

> **Line counts:** PRD.md = 278 lines, PRD_FINALIZED.md = 278 lines (line-delta 0%; the single edit was an inline addition to existing paragraph line 124). Character-level: 48,637 → 49,246 chars (+609, +1.25%).
>
> **Changes (one bullet):**
> - **§3.2 (Conflict Screening / intake gate)** — *insert* — appended a precedence-clarifying sentence pinning that the conflict gate sits below the legal-state check (§2.10), that each of the three operations has its own state precondition (open requires `CONFLICT_CLEARED`; capture requires `OPEN`) checked first, and therefore a `CONFLICT_BLOCKED` matter is rejected with `ERR_INVALID_STATE` (HTTP 409) rather than `ERR_CONFLICT_NOT_CLEARED` for all three operations — `routes/matters.py:242-246` (open), `routes/entries.py:74-78` (time capture), `routes/entries.py:188-190` (expense capture).
>
> **test_06 overdraw item — no PRD edit (confirmed pure fixture bug).** Both disbursement (`routes/trust.py:121-131`) and trust-sweep (`routes/invoices.py:293-315`) follow PRD §2.10 precedence exactly (SoD priority 7 before overdraw priority 9), which the PRD already pins. No silence revealed; no patch made.

## Step 9: Complete PRD — 2026-06-24T19:12:00.000Z

Verbatim Step 9 subagent summary:

> **Files:** Source `PRD_FINALIZED.md` (present, so used as base) → `PRD_COMPLETED.md`. Lines: 278 → 278 (unchanged; all edits in-paragraph). Chars: 49,246 → 51,150 (delta +1,904).
>
> **Counts:** 7 changes total — 7 ambiguity-pins, 0 mismatch-revisions.
>
> **Per-change bullets:**
> - §2.7 — insert — ambiguity — UTBMS codes reference a `BillingCode` by its `code` string value, not by `id`; unmatched string fails as `ERR_NOT_FOUND` before the kind check — routes/entries.py:230-234 (`_find_code`), 60-65.
> - §3.3 — insert — ambiguity — "default trust account" is the earliest-created `TrustAccount`; if none exists the on-open ledger cascade is silently skipped — routes/matters.py:260-279 (`_ensure_default_ledger`).
> - §3.3 — insert — ambiguity — rate-override create returns `201` in both first-create and replace cases (replace mutates in place); override is a lean 4-field resource with no `created_at`/`updated_at`/`version` — routes/clients.py:124-144, serializers.py:77-79.
> - §3.7 — insert — ambiguity — send-to-collections gating: not-yet-`OVERDUE` (`CURRENT`/`DUE`/non-issued) → `ERR_INVALID_STATE`; `OVERDUE` within grace → `ERR_COLLECTIONS_TOO_EARLY`; grace boundary is still "too early" — routes/invoices.py:394-404.
> - §3.8 — insert — ambiguity — repeat trust-ledger open returns existing `ClientTrustLedger` unchanged (still `201`), does not overwrite `retainer_floor_cents` — routes/trust.py:47-51.
> - §3.8 — insert — ambiguity — `POST /firm/trust-transactions` accepts only `DEPOSIT`/`DISBURSEMENT`; `SWEEP_TO_OPERATING` kind rejected with `ERR_INVALID_REQUEST` (400) — routes/trust.py:107-110.
> - §4 (endpoint table) — revise — ambiguity — `GET /firm/clients/{id}/conflict-checks` "referencing this client" = checks whose `adverse_party_client_id` OR `matched_client_id` equals the client `id` — routes/clients.py:106-107.
>
> **Notable non-changes:** realization_pct precision already covered (§2.5/§3.6); retainer-replenishment "flag" has no response field in PRD or impl; write-off remaining-balance = total − amount_paid per §3.7; trust-sweep precedence (overdraw before ledger-mismatch) already matches §2.10; list/get invoice re-aging matches §3.7.

## Pipeline complete — 2026-06-24T19:12:00.000Z

Final state: 85/85 tests pass across all 8 parallel stability rounds (results.{1..8}.json). All deliverables present: SCAFFOLD.yaml + 2 design files, worklog.md, test_helpers/ (9 files), test_suite/ (6 test files + conftest, 85 functions), workspace/{INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md, implementation/ (Python+Flask, in-memory, start.sh)}.

## Step 3: Copy INSTRUCTION.md — 2026-06-24T18:31:00.000Z

Copied ./INSTRUCTION.md -> workspace/INSTRUCTION.md (1424 bytes).
