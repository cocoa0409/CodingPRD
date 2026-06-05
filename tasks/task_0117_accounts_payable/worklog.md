# Worklog — task_0117_accounts_payable

Scenario: Accounts Payable Automation: OCR invoice capture, PO/non-PO coding, approval workflow/threshold, 2/3-way match exception, duplicate detection, payment run (ACH/check/card), early-pay discount, 1099 vendor, accrual

Difficulty: Expert (10–15 entities, 20–32 endpoints, 18–30 error codes, 3+ calculation variants, 4+ state machines)

## Step 1: Create task directory — 2026-06-03T02:31:35.000Z

Created `tasks/task_0117_accounts_payable/` and `tasks/task_0117_accounts_payable/workspace/` (directory pre-assigned; auto-increment scan skipped per directive).

## Step 2: Generate scaffold — 2026-06-03T02:59:00.000Z

Generated all three scaffold artifacts for the Accounts Payable Automation task at **Expert** difficulty:
- `SCAFFOLD.yaml` (1515 lines)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (top-level key `scaffold_difficulty_design`, 1097 lines)
- `SCAFFOLD_CORNER_DESIGN.yaml` (top-level key `scaffold_corner_design`, 1511 lines)

**Counts:**
- **Entities: 13** — Vendor, GLAccount, PurchaseOrder, GoodsReceipt, Invoice, InvoiceLine, MatchException, ApprovalRoute, ApprovalStep, PaymentBatch, Payment, Accrual, AuditEvent
- **Endpoints: 46** — over the 20-32 band; overage structurally forced by 11 FKs each requiring a reverse-reachability GET plus get-by-id collection anchors (documented "Expert endpoint band vs FK reachability" tradeoff); 4 pure-convenience listers trimmed. Lint clean.
- **Error codes: 22**
- **Calculation variants: 5 calculations** — `match_variance` (2-way vs 3-way basis), `early_pay_discount`, `accrual_amount` (estimate vs final), `approval_tier` (tiered), `batch_total` (sum-of-rounded); 4 carry explicit `variants` blocks
- **State machines: 5** — Invoice (cyclic revision loop), ApprovalStep (branching approve/reject + cascade), MatchException (branching resolve/write-off/escalate), PaymentBatch (linear + void revert), Payment (parallel settlement axis)

**Design profile:** Workflow orchestration + Ledger reconciliation; flat topology; branching state shape; segregation-of-duties role model (APManager / APClerk / Approver / Auditor); immediate consistency; OCC on PaymentBatch.version.

**Difficulty design:** all 9 §0.5 rules covered with 2 instances each (18 total). **Corner design:** 40 active instances + `excluded_because` stubs across all 9 claim-extraction sections.

**Independent verification (orchestrator):** `scaffold_lint.py tasks/task_0117_accounts_payable/` → "VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5." (46 endpoints, 13 entities, 18 difficulty instances, 40 corner instances, 431 calls scanned). No design keys leaked into SCAFFOLD.yaml; design files carry correct single top-level keys.

## Step 3: Copy shared files — 2026-06-03T03:00:00.000Z

Copied `INSTRUCTION.md` → `tasks/task_0117_accounts_payable/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-06-03T03:05:00.000Z

Wrote `workspace/PRD.md` (271 lines). Major sections: §1 Introduction (AP automation framing + segregation-of-duties/ledger-conservation philosophy); §2 Global Specs (RBAC 4 roles, verbatim §2.2 envelope, pagination, common props + validation precedence, monetary precision/round-half-up, ledger reconciliation, cascading state effects, nested retrieval, OCC on batch release); §3 Business Logic (master data, goods receipts, invoice capture/coding, match + 3 exception branches, tiered approval, payment-run lifecycle, discount/net/batch-total, period-end accruals, audit trail); §4 Endpoint table (all 46 endpoints); §5 Error catalogue (all 22 error IDs).

Doc-gen self-checks all PASS: field coverage (56/56 entity fields, 35/35 request bodies, OCC field), rule coverage (22 validations incl. priority ordering, OCC rule, all 17 states, 5 calculations w/ constants 1000/0.02/0.80/5000, 33 enums, 12 audit event types), path-purity (§3 has 0 path/method tokens). §2.2 byte-for-byte match to fixed source. Both design index files NOT read.

## Step 5: Generate unit tests — 2026-06-03T03:25:00.000Z

**test_helpers/ — 9 files**: `__init__.py`, `types.py` (entity TypedDicts + status/role enums; `updated_at`/`version` omitted from lightweight records GLAccount/ApprovalRoute/AuditEvent per PRD §2.4), `api_client.py` (one method per PRD §4 endpoint), `api_errors.py` (22 error IDs + HTTP-status map), `assertions.py`, `factories.py`, `constants.py`, `test_users.py` (opaque-identity role headers + per-user-id builders for SoD threading), `fixtures.py` (composite setup chains).

**test_suite/ — 11 files (10 test files + conftest), 76 tests**: master data/capture, invoice state/coding, matching/variance, match exceptions, approval workflow, payment building/discount, release/settle/void, receipts/accruals, access control/errors, listing/audit.

**Design coverage — 100%, zero skips**: all 18 difficulty instances translated (2 tests each = 36), all 40 non-stub corner instances translated (1 test each = 40). 0 skipped — every instance passed the PRD-first two-condition filter. All 8 corner `excluded_because:` stubs verified to cross-reference real difficulty instances; none emitted as tests.

**Verification**: every test docstring ends with exactly one resolving `Design:` tag (no untagged/dual/ghost); every PRD citation verbatim-matched; fixed two listing tests that originally cited the endpoint-table row (C2 violation) to lead with §2.3 prose; no skip/xfail; suite collects cleanly (76 tests); helpers import without error. NOTE: validated at import/collection level only (no server running at gen time).

## Step 6: Generate implementation — 2026-06-03T03:25:00.000Z

Complete Python + Flask impl at `workspace/implementation/`. Files: `start.sh` (executable), `requirements.txt` (flask==3.0.3), `app.py` (registers 11 blueprints, error handlers, binds 0.0.0.0:$PORT), `db.py` (in-memory stores + UUID/timestamp/request-id helpers), `errors.py` (APIError + 22 error-id constants), `response.py` (envelope helpers), `middleware.py` (X-User-ID/X-User-Role auth + RBAC 4 roles), `routes/` (11 blueprints + _helpers.py), `services/` (common, calculations [Decimal round-half-up], ledger, audit).

**Endpoints: 46 wired** — matches scaffold §1.5 / PRD §4.
**Storage: in-memory only** — plain Python dicts keyed by id (13 stores). No SQLite/disk/JSON/tmp. 0 entities at boot; nothing seeded. start.sh re-invocation wipes all state.
**start.sh**: reads $PORT (default 10000), binds 0.0.0.0, `exec python3 app.py` foreground. pip install guarded by `python3 -c "import flask"` sentinel → no-op once Flask present (avoids concurrent-reboot contention). Verified guarded reboot skips pip, responds 200 in <4s.

Impl-gen ran two end-to-end smoke suites (72 assertions, all passing) over full lifecycle. Two PRD-fidelity fixes during verification: (1) add/remove payment bumps batch `version` by exactly one (ledger recompute no longer double-bumps) per §3.6; (2) re-coding from CODING_REVIEW advances straight to MATCHED without re-testing tolerance, and a WRITTEN_OFF exception's zeroed variance persists through recompute (§3.4). Started with empty test dirs (physical isolation confirmed — concurrent launch with Step 5).

## Step 7: Run tests and iterate — 2026-06-03T03:30:00.000Z

**Iterations run:** 2 (initial diagnostic sweep + 1 verification sweep after fixes).

**Diagnosis:** Initial 8-round sweep stable but consistently failed exactly 2 tests in all 8 rounds (74/76). Both were "priority-pair" tests whose assertions trace to the SCAFFOLD's numeric validation-priority table, which contradicts the authoritative PRD prose precedence.

**Tests deleted (both: ERROR PRECEDENCE SILENCE, STEP 1b):**
1. `test_double_schedule_same_invoice_rejected` (test_06_payment_building_and_discount.py) — Asserted `ERR_INVOICE_ALREADY_SCHEDULED` when re-adding an already-SCHEDULED invoice to a second batch. But PRD §2.4 mandates `ERR_INVALID_STATE` (state-machine legality) be evaluated before any Section-3 business rule, and PRD §3.6 makes APPROVED a state precondition of add-payment. Any invoice with a live payment is necessarily non-APPROVED, so a faithful PRD-only implementer returns `ERR_INVALID_STATE` and never reaches the priority-12 already-scheduled check. PRD contradicts rather than uniquely determines the asserted outcome. (Scaffold rule: validations priority 12.)
2. `test_segregation_outranks_stale_version_on_release` (test_07_release_settle_void.py) — Asserted `ERR_SEGREGATION_OF_DUTIES` wins over `ERR_STALE_BATCH_VERSION` when both fire. Both are post-state Section-3 business rules; PRD §2.4 does not rank business rules among themselves, and the only ordering signal in PRD prose (§3.6's textual sequence) lists the OCC version check FIRST. A faithful implementer returns `ERR_STALE_BATCH_VERSION` — opposite of the assertion. SoD alone remains covered by `test_segregation_of_duties_blocks_self_releaser`; OCC-stale alone by `test_occ_stale_version_release_rejected`. (Scaffold rule: validations priority 9 vs 18 — priority table contradicts PRD prose order.)

**Fixes applied to `test_helpers/`:** None.
**Fixes applied to `implementation/`:** None. Implementation already follows PRD §2.4 precedence (state-before-business-rules) and PRD §3.6 textual order (OCC version → empty → SoD) correctly; reordering to satisfy the deleted tests would make it LESS faithful to PRD.

**Final confirmation:** All 8 parallel rounds passed == total at **74/74** (0 failed, 0 errors each). Orchestrator independently re-verified all 8 results.*.json: round 1–8 each 74/74, failed 0, errors 0; 74 test functions remain in test_suite/.

## Step 8: Finalize PRD — 2026-06-03T03:35:00.000Z

Produced `workspace/PRD_FINALIZED.md`. Line counts: PRD.md = 271, PRD_FINALIZED.md = 271 (Δ 0 lines; 1 line revised in place, ~70 words added).

**Changes (1 edit):**
- §3.6 (Payment Runs — Releasing) — *revise* — Pinned evaluation precedence among the three release-time business checks: OCC version match → non-empty → segregation of duties; when multiple conditions fail, the first in that order is reported (stale version beats empty and SoD; empty beats SoD). Scoped to "these three release-time checks" so it does not contradict global §2.4 (ERR_INVALID_STATE-before-business-rules; BUILDING-state check still runs ahead, untouched). Source: `routes/payment_batches.py:192-202` (sole release path; all three error symbols appear only here).

**Item 1 (deleted test_double_schedule_same_invoice_rejected) — NO edit:** PRD §2.4 already mandates ERR_INVALID_STATE before any Section-3 business rule, and §3.6 frames APPROVED as the add-payment source state; a SCHEDULED invoice fails the state precondition → ERR_INVALID_STATE, exactly as impl does (`routes/payment_batches.py:add_payment` 104-105 fires before already-scheduled check 119-125). PRD already uniquely determines; no edit.

**NO-NEW-MISMATCH search (item 2):** grepped all three error symbols + release/RELEASED/expected_paymentbatch_version across implementation/ — single code path (`release_batch` 169-217); wording scoped to the three checks to leave global §2.4 precedence and the preceding BUILDING-state check intact.

## Step 9: Complete PRD — 2026-06-03T03:40:00.000Z

Produced `workspace/PRD_COMPLETED.md` from PRD_FINALIZED.md. Lines: 271 → 271 (unchanged). Chars: 41,865 → 42,628 (+763). 4 changes: 2 ambiguity-pins, 2 mismatch-revisions.

**Changes (all in-paragraph, no new sections):**
- §3.1 GL account — insert — ambiguity — duplicate `code` → `ERR_INVALID_REQUEST` (was silent on rejection error) — `routes/gl_accounts.py:36-38`
- §3.1 Purchase order — revise — mismatch — PRD said "missing" `gl_account_code` → `ERR_GL_ACCOUNT_NOT_POSTABLE`, but impl's required-field check fires first; pinned absent field → `ERR_INVALID_REQUEST` (per §2.4 precedence), present-but-unknown/non-postable → `ERR_GL_ACCOUNT_NOT_POSTABLE` — `routes/purchase_orders.py:26,41-44`
- §3.1 Approval route — revise — mismatch — bare "Tiers must not overlap" implied creation-time overlap validation impl does not perform; pinned that creation validates only `max_amount_cents` strictly > `min_amount_cents` (`ERR_INVALID_REQUEST` else) and does NOT reject overlapping tiers — `routes/approval_routes.py:32-37`
- §3.5 Tiered approval — insert — ambiguity — "the single approval route" ambiguous when tier table overlaps; pinned first-match in route-creation order — `routes/invoices.py:315-319`

**Behaviors confirmed already-pinned (no change):** entity field shapes/enums; add-payment guard order (method-mismatch → on-hold → already-scheduled); release guard order (version → empty → SoD); variance basis per match_type + tolerance strict-greater-than; revision-loop re-code → MATCHED with write-off-absorbed variance preserved; discount on-or-before-deadline equality; accrual closed-interval / receipt half-open overlap; `ytd_1099_paid_cents` plain accumulation.

Step 9 edits PRD_COMPLETED.md only — implementation/ and tests untouched, so the 8-round green sweep (74/74) remains valid.

---

## Pipeline complete — task_0117_accounts_payable

Final state: 74/74 tests passing across all 8 parallel rounds. Artifacts: SCAFFOLD.yaml (+ DIFFICULTY/CORNER design), worklog.md, test_helpers/ (9 files), test_suite/ (74 tests / 10 files + conftest), workspace/{INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md, implementation/}. Expert difficulty: 13 entities, 46 endpoints, 22 error codes, 5 calculations, 5 state machines.
