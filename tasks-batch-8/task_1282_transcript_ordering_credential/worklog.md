# Worklog — task_1282_transcript_ordering_credential

## Step 1: Create task directory — 2026-08-12T19:23:00.000Z

Task directory `tasks/task_1282_transcript_ordering_credential/` and `workspace/` were pre-created and pre-assigned by the pipeline (Step 1 treated as DONE per invocation args). No index scan performed; no other task_* directory touched. User directive: difficulty harder than expert level.

## Step 2: Generate Scaffold — 2026-08-12T20:00:30.000Z

All three artifacts generated and lint-clean.

## Summary

**Output directory:** `/home/ubuntu/github/CodingPRD/tasks/task_1282_transcript_ordering_credential/`

**Files written:**
- `SCAFFOLD.yaml` — §1.0–§1.7 (no `scaffold_difficulty_design` / `scaffold_corner_design` keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level key `scaffold_difficulty_design:`
- `SCAFFOLD_CORNER_DESIGN.yaml` — single top-level key `scaffold_corner_design:`

**Artifact stats (SCAFFOLD.yaml):**
- Entities: 15 (Student, StudentRecord, Recipient, Hold, IdentityVerification, TranscriptOrder, OrderLineItem, ArchivedRecordRetrieval, ConsentGrant, VerificationRequest, FeeSchedule, Payment, ReissueRequest, ClearinghouseReportBatch, AuditEvent)
- State machines: 10 (incl. parallel `fulfillment_status` × `payment_status` dimensions on TranscriptOrder, and a dedicated `TranscriptOrder.payment_status` machine) with 44 total transitions
- Calculations: 8 (fee_quote_provisional, fee_quote_final, rush_qualification, verification_fee, payment_capture_reconcile, order_refund_on_failure, gpa_cents_recompute, clearinghouse_sweep)
- Validations: 20 (priorities 1–20, spanning auth/existence/state/business_safety/business_constraint/business_temporal/business_referential/business_fiscal)
- Endpoints: 77
- Errors: 26
- Roles: 8 (Student entity-backed; 7 opaque operator/admin roles)
- Concurrency rules: 2 (OCC on TranscriptOrder for submit and line-item-add)

**§1.8 difficulty design:** 18 instances total, 2 per each of the 9 rules, honoring every differentiation clause:
- dual_variant_calc: order fee (TranscriptOrder domain, provisional vs final diverge across schedule window roll) vs verification fee (VerificationRequest domain, archived vs non-archived subject diverge)
- combinatorial_formula: per-line-rounding (mode b) vs tiered+rush-multiplier+rush-flat with pinned evaluation order (mode a)
- non_linear_state_machine: TranscriptOrder parallel dimensions vs ClearinghouseReportBatch FAILED→re-sweep cycle
- transitive_cascade: Hold release→order→line items (depth 3) vs ConsentGrant revoke→VerificationRequest deny (depth 2)
- priority_pair_validation_conflict: state vs business_fiscal and business_safety vs business_referential pairs
- boundary_precision_check: rush cutoff strict `<` at 14:00:00 vs volume tier `>=` at min_copies
- cross_entity_state_dependency: TranscriptOrder↔Hold and VerificationRequest↔ConsentGrant (different pairs)
- resource_temporal_overlap: FeeSchedule half-open interval-overlap vs IdentityVerification point-in-interval expiry
- compensating_invariant: Payment captured−refunded invariant vs clearinghouse membership conservation across FAILED batches

**§1.9 corner design:** 38 instances (35 active + 3 excluded_because stubs) across all 9 claim-extraction-guide sections: entities (8), state_machines (6), calculations (3), validations (6), endpoints (2), errors (4 incl. 3 stubs), RBAC (3), cross-cutting layers (5), consistency_model (1).

**Lint verdict (verbatim):**
```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
Coverage: 77 endpoints, 15 entities, 18 §1.8 instances, 35 §1.9 active instances, 455 calls scanned.

## Step 3: Copy Shared Files — 2026-08-12T20:01:00.000Z

Copied ./INSTRUCTION.md to tasks/task_1282_transcript_ordering_credential/workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-08-12T20:08:00.000Z

PRD generated and all three hard contracts pass.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1282_transcript_ordering_credential/workspace/PRD.md` — 296 lines.

**Section structure**
- §1 Introduction (3 paragraphs, system-goals + dual-surface + reader-guidance angle)
- §2 Global Specifications (8 subsections): 2.1 RBAC with per-role `identity:` translation; 2.2 verbatim response-envelope block; 2.3 Pagination; 2.4 Common resource properties + logical clock (including the `IdentityVerification`/`AuditEvent` `common_fields: false` deviation and clock-default `2026-08-01T00:00:00Z`); 2.5 Validation priority ladder (all 20 priorities in order); 2.6 OCC (both rules named: order-submit and line-item-add, both `expected_order_version` + `ERR_STALE_VERSION` + 412); 2.7 Precision/rounding/money; 2.8 Soft-deactivation + append-only audit
- §3 Business Logic & Workflows (11 subsections, freely grouped by lifecycle): 3.1 students/record snapshots/GPA recompute; 3.2 holds + office segregation + 365-day auto-expire; 3.3 order drafting, recipient routing, rush 5-condition conjunction (strict-before 14:00, weekday, non-holiday, no PAPER_MAIL); 3.4 identity verification (72-hour token); 3.5 submit + hold-check + pinned fee-quote pipeline (per-line round-then-sum, volume-tier tie-break, rush multiplicative-then-additive); 3.6 payments (authorize/capture with min-target reconciliation, four-hour rush grace drop, refund waterfall, void); 3.7 dispatch/delivered/bounced + order bubble-up; 3.8 archived retrieval (48-hour SLA); 3.9 verification requests + FERPA consent + 4-check approval order + fee constants (500/300/700/1500); 3.10 reissue with segregation-of-duties and replacement-order fan-out; 3.11 clearinghouse sweep (period inclusion, no-resweep, created_at tie-break, FAILED-unlock compensation)
- §4 Endpoint table (4 columns, 76 rows) with one-paragraph status-code rule
- §5 Error catalogue (2 columns, 26 rows)

**Contract reports**
- Contract 1 (Field-Name Coverage): required=100 backticked identifiers (entities + request/query/path params + quote-preview output keys + common fields), all present, 0 missing — PASS after repairing 5 initial gaps (`code`, `current_utc`, `display_name`, `replacement_order_id`, `retrieval_status`).
- Contract 2 (Rule Coverage): all 26 `error_id` values appear in §2/§3 narrative in addition to §5; all 13 audit-action IDs (`ORDER_SUBMIT`, `ORDER_CREATED`, `ORDER_CANCELLED`, `ORDER_DELIVERED`, `ORDER_FAILED`, `HOLD_RELEASE`, `HOLD_RELEASED`, `HOLD_CLEARED`, `IDENTITY_VERIFIED`, `IDENTITY_REJECTED`, `STUDENT_CREATED`, `STUDENT_UPDATED`, `REISSUE_APPROVED`) named at their firing points; all state enum values across 10 state machines present; both OCC rules named with endpoint framing + `expected_order_version` + `ERR_STALE_VERSION` + 412; the four-check verification-approval ordering is explicitly rendered ("First … Second … Third … Fourth"); depth-3 hold-release cascade and depth-2 clearinghouse cascade both expressed — PASS.
- Contract 3 (§3 Path Purity): 548 backticked tokens scanned inside §3, 0 path-shaped, 0 bare-HTTP-method, 0 method+path combos — PASS.

**Scaffold coverage:** 16 entities, 10 state machines (including the parallel `payment_status` dimension), 8 calculations (fee_quote_provisional, fee_quote_final, rush_qualification, verification_fee, payment_capture_reconcile, order_refund_on_failure, gpa_cents_recompute, clearinghouse_sweep), 20 validation rules in priority order, 2 concurrency rules, 76 endpoints, 26 errors, 8 roles — all expressed in prose.

## Step 5: Generate Unit Tests — 2026-08-12T20:35:00.000Z

Generation complete. All audits pass.

## Summary

**test_helpers/ (9 files written)**
- `types.py` — 14 entity TypedDicts + 16 status/role enums; `IdentityVerification` and `AuditEvent` correctly omit `updated_at`/`version` (common_fields: false)
- `api_client.py` — `ApiClient(GenericApiClient)` with all 52 PRD §4 endpoints
- `api_errors.py` — 26 error IDs + HTTP status map, registered via `set_error_http_status_map`
- `assertions.py` — per-entity assert functions + `assert_payment_invariants` (refund waterfall)
- `factories.py`, `constants.py`, `test_users.py` (shared constants + mandatory `make_student_headers` per-instance builder for the entity-backed Student role)
- `fixtures.py` — composite helpers: `reset_clock`/`set_clock`, `create_fee_schedule`, `create_student`, `create_recipient`, `publish_record`, `create_draft_order` (OCC-threaded line adds), `create_verified_identity`, `create_submitted_order`, `create_authorized_payment`, `create_captured_payment`, `create_delivered_order`, `create_hold`, `create_consent_grant`, `create_verification_request`, `create_verification_in_consent_check`, `create_batch`, `create_reissue_request`
- `__init__.py` — barrel export

**test_suite/ (9 files, 72 tests)**
- `conftest.py` + `test_01_students_and_records.py` (8) + `test_02_identity_and_holds.py` (7) + `test_03_order_workflows.py` (7) + `test_04_fees_and_rush.py` (11) + `test_05_consent_and_verification.py` (9) + `test_06_payments_and_occ.py` (6) + `test_07_hold_cascade_and_clearinghouse.py` (9) + `test_08_admin_and_reissue.py` (9)

**Coverage: Queue A (Difficulty)** — 18/18 instances, all with ≥2 tests (36 tests). **Queue B (Corner)** — 33/33 non-stub instances, all with ≥1 test (36 tests); the 3 `excluded_because` stubs (`err_invalid_request_triggerable`, `err_not_found_triggerable`, `err_invalid_state_triggerable`) were not translated, per spec.

**Verification performed:** all files compile; pytest collects 72 tests; every Design tag resolves to a real instance and is the unique last docstring line; every quoted PRD citation span (≥20 chars) survives a whitespace-normalized literal grep of PRD.md (0 failures); all `from test_helpers import` names resolve; no skip/xfail markers; no scaffold references in generated code.

**Key adjudications (PRD-first):**
- `fee_schedule_window_overlap_on_active_schedules_rejected`: the recipe's `ERR_SCHEDULE_WINDOW_INVALID`-on-overlap assertion contradicts PRD §2.8 (overlap triggers atomic deactivation, not rejection). Tests assert the PRD behavior instead — overlap deactivates the prior schedule; adjacent half-open windows coexist. Inverted-window rejection (PRD-stated) is covered by the corner instance.
- `order_parallel_payment_and_fulfillment_dimensions`: the recipe's expected `ERR_INVALID_STATE` on unpaid dispatch is grounded in PRD §3.7's gating sentence (CAPTURED-or-WAIVED requirement) even though §3.7 doesn't name the error id — §2.5 pins `ERR_INVALID_STATE` as the state-rung error, so the outcome is uniquely derivable.
- Idempotency tests use same-key-different-payload (409) and same-key-same-payload (returns original), both verbatim-covered in PRD §3.6.

## Step 6: Generate Implementation — 2026-08-12T20:55:00.000Z

Done. The implementation is complete and verified against fresh `bash start.sh` boots.

## Summary

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1282_transcript_ordering_credential/workspace/implementation/`):

- `start.sh` — foreground launcher, `exec python3 app.py`, dependency install guarded by `python3 -c "import flask"` so per-test reboots don't re-run pip
- `requirements.txt` — `flask>=3.0,<4`
- `app.py` — Flask entry point, `0.0.0.0:$PORT` (default 10000), `ApiError`/404/405/generic handlers
- `db.py` — in-memory store (15 collections, starts empty on every boot, no seeding), logical clock state defaulting to exactly `2026-08-01T00:00:00Z`
- `errors.py`, `response.py`, `middleware.py`, `util.py` — error type, PRD §2.2 envelope (`meta.api_request_id`/`api_request_timestamp` + `response_type` + `data`, list pagination fields `limit`/`offset`/`total_count`/`has_more`), `X-User-ID`/`X-User-Role` auth with all 8 roles, validation/parsing helpers
- `services.py` — serializers, common-fields helpers (`created_at`/`updated_at`/`version`; `IdentityVerification` and `AuditEvent` carry only `id`+`created_at` per PRD §2.4), audit emission with SHA-256 `payload_hash`, hold-block evaluation, rush qualification, tiered fee quoting, final-fee reconciliation, order bubble-up, hold-release depth-3 cascade, clock-driven sweeps, clearinghouse sweep
- `routes/` — 13 blueprints: students, recipients, holds, identity, orders, line_items, payments, consent, verification, retrievals, reissues, clearinghouse, admin (fee schedules + audit events + `_clock/set_current_utc`)

**Endpoint count:** 77 routes registered, covering all 76 rows in the scaffold §1.5 table plus the Flask preflight automatics.

**State machines implemented:** 10 — TranscriptOrder fulfillment (DRAFT→SUBMITTED→HOLD_CHECK/READY_TO_FULFILL→IN_TRANSIT→DELIVERED/FAILED, plus REISSUE_PENDING loop and cancellation), parallel TranscriptOrder payment dimension (UNPAID→AUTHORIZED→CAPTURED→PARTIALLY_REFUNDED→REFUNDED, VOIDED, WAIVED), OrderLineItem, Hold (with 365-day zero-amount FINANCIAL auto-expiry), IdentityVerification (72h token expiry with order-cancel cascade), ConsentGrant (revoke/expire cascades denying in-flight CONSENT_CHECK requests), VerificationRequest, ArchivedRecordRetrieval (48h SLA enforcement), ClearinghouseReportBatch (with mark-failed compensating reversion of REPORTED→APPROVED), ReissueRequest (including auto-FULFILLED when the replacement order delivers).

**Notable design decisions:**

- **Logical clock, never wall-clock** for all domain timestamps and time-sensitive evaluation; wall clock is used only for the envelope's `api_request_timestamp`. Clock default is exactly `2026-08-01T00:00:00Z` at startup.
- **Fee math in `Decimal` with round-half-up** at each pinned step: per-line unit price rounded before summing, volume tier picked by highest satisfied `min_copies` (first-listed wins on tie), rush applied multiplicatively then additively. Final fee reprices against the capture-time schedule, drops rush components past cutoff+4h grace, and short-circuits to 0 for fee-waived reissue replacements.
- **Validation ordering** follows the PRD §2.5 ladder: auth → RBAC → path existence (404) → body FK existence (ERR_REFERENCED_NOT_FOUND) → state (409) → OCC (412) → business rules; unknown request fields are rejected as `ERR_INVALID_REQUEST` (400) so stray `expected_*_version` fields on non-OCC endpoints fail shape validation.
- **Cascades**: hold release and clock-driven hold expiry re-evaluate HOLD_CHECK orders and fan PENDING line items to QUEUED; identity reject/expire cancels IDENTITY_PENDING orders; consent revoke/expire denies in-flight verification requests with `CONSENT_REVOKED`/`CONSENT_EXPIRED`; batch transmit moves swept APPROVED verifications to REPORTED and mark-failed reverts them (compensating action, so the next sweep re-includes the same items).
- **Idempotency** on `POST /registrar/payments`: same key + same payload returns the original Payment (201); same key + different payload yields `ERR_IDEMPOTENCY_CONFLICT` (409).
- **OCC** via `expected_order_version` on order submit and line-item add only, per scaffold §1.2.1.
- **Segregation of duties** enforced on reissue approve/reject and verification approve (reviewer `X-User-ID` must differ from the student id), and office-matched hold placement/release (FINANCIAL→BursarOffice, LIBRARY→LibraryOffice, REGISTRAR/DISCIPLINARY→RegistrarAdmin).

Verified by three smoke suites (~120 assertions total) run against independent fresh `bash start.sh` boots: full order lifecycle (draft→line items→identity→submit→hold→release→authorize→capture→dispatch→delivered→reissue→replacement delivered), rush/volume-tier quote math with exact cent expectations, refunds and refund-overflow rejection, archive retrieval with SLA breach, consent revoke/expiry cascades, clearinghouse sweep/lock/transmit/ack/fail-re-sweep, RBAC denials, 401/404/409/412/422 error catalog coverage.

## Step 7: Run Tests and Iterate — 2026-08-12T21:10:00.000Z

All 8 rounds pass 72/72. Task complete.

## Summary

- **Iterations run:** 2 (initial sweep: 67/72 in all 8 rounds with 5 deterministic failures; post-fix sweep: 72/72 × 8 rounds, zero flakiness).
- **Tests deleted:** none — every failing test traced to a verbatim PRD rule; no PRD-silence or unique-derivability collapses found.
- **Fixes applied to `test_suite/`** (test bugs, STEP 2 — assertions contradicted PRD):
  - `/home/ubuntu/github/CodingPRD/tasks/task_1282_transcript_ordering_credential/test_suite/test_04_fees_and_rush.py` — `test_quote_preview_returns_provisional_estimate`: asserted `order.quoted_fee_cents == 0` after a preview, contradicting PRD §3.3 ("each successful add … recomputes … the provisional `quoted_fee_cents`", so the add already persists 1000). Fixed to express the actual §3.3 "not persisted" rule: capture order state before the preview and assert `quoted_fee_cents` and `version` are unchanged across the preview call.
  - `/home/ubuntu/github/CodingPRD/tasks/task_1282_transcript_ordering_credential/test_suite/test_04_fees_and_rush.py` — `test_order_fee_provisional_vs_final_diverge_when_schedule_window_rolls`: asserted `captured_cents == 1200` where the authorization was 1000, contradicting PRD §3.6 ("The captured amount is the smaller of the authorized `amount_cents` and that target — a capture can never exceed the authorization … the shortfall is recorded but not auto-charged"). Fixed to expect `captured_cents == 1000` and added the PRD-required companion assertion that capture reconciles `amount_cents` to the recomputed `final_fee_cents` (1200).
- **Fixes applied to `implementation/`** (STEP 3):
  - `/home/ubuntu/github/CodingPRD/tasks/task_1282_transcript_ordering_credential/workspace/implementation/routes/identity.py` — `confirm_idv`: expiry check now precedes the generic not-PENDING state check, so a confirm after expiry yields `ERR_VERIFICATION_EXPIRED` (422) per PRD §3.4 ("A confirm attempted after expiry is rejected with `ERR_VERIFICATION_EXPIRED`") instead of `ERR_INVALID_STATE`.
  - `/home/ubuntu/github/CodingPRD/tasks/task_1282_transcript_ordering_credential/workspace/implementation/routes/orders.py` — `add_line_item`: provisional-quote recompute at add time now runs with `persist_unit_prices=True`, storing each line's rounded `unit_price_cents` per PRD §3.5 ("that per-line rounded figure is stored on the line as `unit_price_cents`") combined with §3.3's add-time recompute.
  - `/home/ubuntu/github/CodingPRD/tasks/task_1282_transcript_ordering_credential/workspace/implementation/routes/payments.py` — `authorize_payment`: idempotency-key registry is now global (scans all payments) instead of scoped per order; PRD §3.6's "already seen with a different payload" is only reachable across orders since the authorize payload is just `{order_id, idempotency_key}`, so key reuse on a different order correctly raises `ERR_IDEMPOTENCY_CONFLICT` (409).

## Step 8: Finalize PRD — 2026-08-12T21:18:00.000Z

`PRD_FINALIZED.md` written at `/home/ubuntu/github/CodingPRD/tasks/task_1282_transcript_ordering_credential/workspace/PRD_FINALIZED.md`.

## Line counts
- `PRD.md`: 296 lines; `PRD_FINALIZED.md`: 296 lines (0% delta — all three changes are in-place sentence revisions, no new sections).

## Changes (one bullet per edit)
- §3.3 — revise — add-time provisional recompute now pinned to also store each line's rounded `unit_price_cents` on the line (previously §3.3 said only that the add "recomputes … the provisional `quoted_fee_cents`", leaving per-line persistence at add time undetermined) — `implementation/routes/orders.py:200-208` (`compute_quote(..., persist_unit_prices=True)` in `add_line_item`).
- §3.4 — revise — expiry rejection on confirm now explicitly takes precedence over the generic not-`PENDING` state rejection, covering a record already in `EXPIRED` (§2.5's ladder otherwise places `ERR_INVALID_STATE` before `ERR_VERIFICATION_EXPIRED`, leaving the EXPIRED-record case undetermined) — `implementation/routes/identity.py:132-139`.
- §3.6 — revise (two sentences in one paragraph) — "unique per order" replaced with a global cross-order key registry, and the "different payload" clause pinned to mean key reuse on a different `order_id` (under per-order scoping the conflict branch would be unreachable, since the authorize payload is only `{order_id, idempotency_key}`) — `implementation/routes/payments.py:49-63`.

The two `test_suite/` fixes needed no PRD edit: §3.3 already pins "the result is advisory only, is not persisted", and §3.6 already pins "a capture can never exceed the authorization … the shortfall is recorded but not auto-charged" plus "reconciles `amount_cents` to the recomputed `final_fee_cents`" — both were pure assertion bugs.

## Per-edit pre-edit search log

**Edit 1 (§3.4 confirm precedence)**
- (a) Subject: error precedence on `POST /registrar/identity-verifications/{id}/confirm`.
- (b) Paths enumerated: `routes/identity.py:121-155` (`confirm_idv` — expiry check at line 134 fires on `status == "EXPIRED"` *or* `now >= expires_at`, before the not-PENDING check at 138); `routes/identity.py:158-171` (`reject_idv` — no expiry special-casing, EXPIRED → `ERR_INVALID_STATE`); `services.py:762-772` (clock cascade `PENDING` → `EXPIRED`).
- (c) Adjustment: wording scoped to the confirm operation only (so `reject_idv` is untouched) and phrased "even when the record has already left `PENDING`, including one already sitting in `EXPIRED`" rather than naming only `EXPIRED`, because the impl's `now >= expires_at` branch also fires for `VERIFIED`/`REJECTED` records past expiry — a narrower claim would have been a new mismatch.

**Edit 2 (§3.3 add-time `unit_price_cents` persistence)**
- (a) Subject: which quote recomputations persist per-line `unit_price_cents`.
- (b) Paths enumerated (grep for `unit_price_cents` / `compute_quote` / `persist_unit_prices`): `routes/orders.py:186-210` (`add_line_item`, persists); `routes/orders.py:282-291` (`submit_order`, persists — already covered by §3.5); `routes/orders.py:111-130` (`quote_preview`, `persist_unit_prices=False`, no order mutation); `services.py:635-659` (`compute_final_fee` at capture, does not persist); `routes/reissues.py:131-144` (replacement lines copy `unit_price_cents` verbatim from the original).
- (c) Adjustment: claim tied to "the same per-line pricing pipeline described in §3.5" rather than an unconditional "stores", because at add time with no active schedule the pipeline returns early and nothing is stored (impl leaves `quoted_fee_cents` unchanged and the new line at 0); preview's "not persisted" sentence left intact so the preview path stays correctly described; capture and reissue paths are not covered by the sentence and remain uncontradicted.

**Edit 3 (§3.6 global idempotency registry)**
- (a) Subject: scope of the authorize-payment `idempotency_key` registry.
- (b) Paths enumerated (grep `idempotency`): `routes/payments.py:34-63` (`_payload_fingerprint` hashes only `order_id`; loop at line 54 scans all of `DB["payments"]`, so same key + same `order_id` returns the original, same key + different `order_id` → 409); `services.py:445` (serializer only); no other endpoint accepts an idempotency key.
- (c) Adjustment: replaced "unique per order" with the global-registry statement and rewrote the conflict clause as "a key first used on one order being presented against another order", with the replay clause narrowed to "(that is, the same `order_id`)" — matching the fingerprint exactly. No claim made about check ordering (impl runs the registry scan before the fulfillment-state gate; §2.5 lists state before idempotency — left unpinned, as Step 7 did not exercise it and a looser PRD is recoverable).

## Step 9: Complete PRD — 2026-08-12T21:45:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1282_transcript_ordering_credential/workspace/PRD_COMPLETED.md` produced from `PRD_FINALIZED.md` (which existed) with a minimal inline patch aligned to `implementation/`.

**Source vs output:** PRD_FINALIZED.md 296 lines / 50,554 chars → PRD_COMPLETED.md 298 lines / 57,807 chars (+2 lines, +7,253 chars; the +2 lines come from splitting §2.8 into two paragraphs).

**Counts:** 32 ambiguity-pins (inserts), 15 mismatch-revisions.

**Changes (one per bullet):**

- §2.1 — revise — mismatch — narrowed Student ownership enforcement to exactly the ConsentGrant-revocation check; other student-initiated operations accept any existing `student_id` — consent.py:102 (only ownership check in impl).
- §2.2 — insert — ambiguity — `api_request_id` pinned as `req_` + twenty random alphanumerics — response.py:13-15.
- §2.3 — insert — ambiguity — non-integer/out-of-range `limit`/`offset` rejected `ERR_INVALID_REQUEST` 400 — util.py:115-137.
- §2.3 — insert — ambiguity — `has_more` = `offset + limit < total_count` — response.py:29.
- §2.3 — insert — ambiguity — list sort ties on `created_at` broken by `id` ascending — services.py:226-230.
- §2.3 — insert — ambiguity — field-equality query filters honored, unknown query params ignored — all list handlers (e.g., orders.py:84-98, holds.py:106-114).
- §2.4 — insert — ambiguity — all entity timestamps (`created_at`, `updated_at`, `placed_at`, `released_at`, `submitted_at`, IDV `expires_at`, `sla_due_at`, `transmitted_at`, `recorded_at`) read the logical clock; only `meta.api_request_timestamp` is wall-clock — services.py:94-105, db.py:31-39, response.py:7.
- §2.4 — insert — ambiguity — clock-set target instant may be earlier or later — admin.py:176-184.
- §2.5 — revise — mismatch — ladder rewritten to impl's actual order: shape validation (400) now sits after path-existence and before body-FK existence (not last); state rung includes `ERR_ORDER_NOT_DRAFT`; added recipient-active rung; endpoint-specific orders (§3.4–§3.10) explicitly override — e.g., orders.py:148-166, holds.py:51-71.
- §2.7 — insert — ambiguity — "local registrar time" is the UTC reading of the logical clock — services.py:531-538.
- §2.8 — insert — ambiguity — fee-schedule registration validation: inverted window → `ERR_SCHEDULE_WINDOW_INVALID` 422, duplicate `code` → `ERR_INVALID_REQUEST` 400 — admin.py:78-90.
- §2.8 — revise — mismatch — "every mutating action emits an AuditEvent" replaced with the exact 12-action enumeration impl emits (`STUDENT_CREATED/UPDATED`, `HOLD_RELEASED`, `IDENTITY_VERIFIED/REJECTED`, `ORDER_CREATED/SUBMIT/CANCELLED/DELIVERED/FAILED`, `HOLD_CLEARED` on every OFFICIAL advance to READY_TO_FULFILL, `REISSUE_APPROVED`); everything else emits nothing; fixed example `HOLD_RELEASE`→`HOLD_RELEASED` — emit_audit call sites (holds.py:158, identity.py:145/165, orders.py:75/294/333, services.py:680-686/714/735, students.py:100/147, reissues.py:150).
- §3.2 — insert — ambiguity — placement office mismatch → `ERR_HOLD_OFFICE_MISMATCH` 403; negative `amount_cents` → 400 — holds.py:57-71.
- §3.3 — insert — ambiguity — add-line accepts optional `archived_retrieval_id` (FK-checked 404) — orders.py:145,161-166.
- §3.3 — revise — mismatch+ambiguity — dropped "for PICKUP ... all three are null" (impl stores supplied fields); pinned recipient-registration routing requirement → `ERR_RECIPIENT_ROUTING_INVALID` 422 — recipients.py:47-59.
- §3.3 — insert — ambiguity — add-time recompute with no covering schedule: add succeeds, `rush_qualified` recomputed, unit prices/`quoted_fee_cents` unchanged — orders.py:204-209.
- §3.3 — insert — ambiguity — pre-submit rush time/weekday/holiday conditions evaluated against current logical clock; holiday calendar is empty — orders.py:205, services.py:83.
- §3.3 — insert — ambiguity — quote preview: non-DRAFT → `ERR_INVALID_STATE` 409; no covering schedule → `ERR_INVALID_REQUEST` 400 — orders.py:115-123.
- §3.4 — insert — ambiguity — confirm check order after expiry: state (409) then token; token mismatch → `ERR_INVALID_REQUEST` 400 — identity.py:134-143.
- §3.4 — insert — ambiguity — confirm cascade uses the OFFICIAL-only blocking-hold evaluation of §3.5 — identity.py:148-154, services.py:522-524.
- §3.5 — revise — mismatch — submit precondition order pinned as DRAFT (409) → OCC (412) → ≥1 line (400) → VERIFIED identity (422) — orders.py:262-280.
- §3.5 — insert — ambiguity — submit with no covering schedule → `ERR_INVALID_REQUEST` 400, leaving the DRAFT order with the failed attempt's `submitted_at`/`rush_qualified` still visible — orders.py:282-289.
- §3.5 — revise — mismatch — removed the unreachable `ERR_HOLD_BLOCKING`/`ERR_NO_BLOCKING_HOLD` "manual push/advance" claims and the "student is notified" side effect; orders leave HOLD_CHECK only via the §3.2 cascade — no such endpoints in routes/.
- §3.6 — insert — ambiguity — idempotency registry consulted before state/duplicate-payment checks; same-key replay returns original Payment with HTTP 201 — payments.py:54-63.
- §3.6 — insert — ambiguity — capture on non-AUTHORIZED payment or CANCELLED order → `ERR_INVALID_STATE` 409 — payments.py:122-126.
- §3.6 — insert — ambiguity — capture with no covering schedule falls back to `quoted_fee_cents` as final fee — services.py:658-659.
- §3.6 — revise — mismatch — capture caps at the authorized amount instead of rejecting with `ERR_CAPTURE_EXCEEDS_AUTHORIZED`; shortfall visible in reconciled `amount_cents`, capture never moves `fulfillment_status` (was "remains in READY_TO_FULFILL until a supplemental authorization arrives", which impl's duplicate-payment rule makes impossible) — payments.py:135-147.
- §3.6 — insert — ambiguity — refund requires positive integer (400) and CAPTURED/PARTIALLY_REFUNDED state (409) — payments.py:156-164.
- §3.6 — insert — ambiguity — void on non-AUTHORIZED payment → `ERR_INVALID_STATE` 409 — payments.py:188-189.
- §3.7 — revise — mismatch — dispatch does not re-validate routing fields (dropped `ERR_RECIPIENT_ROUTING_INVALID`-at-dispatch claim) — line_items.py:61-92.
- §3.7 — revise — mismatch — `cancelled_reason` is optional, stored null when omitted (was "the caller supplies") — orders.py:311-313.
- §3.8 — revise — mismatch — archive-bound lines fan out to QUEUED at READY_TO_FULFILL like all lines (were "stays in PENDING until the archive produces the record") — services.py:666-671.
- §3.8 — insert — ambiguity — attach-record evaluates the PULLED state check before the `digitized_record_id` reference check — retrievals.py:125-135.
- §3.8 — revise — mismatch — mark-failed has no cascade (was "dependent line items remain PENDING ... until an operator cancels them"; no per-line cancel exists) — retrievals.py:171-179.
- §3.8 — revise — mismatch+ambiguity — SLA gate pinned: applies to mark-pulled/attach-record/attach-to-order only, strictly past `sla_due_at`; no escalation mechanism; mark-failed not gated (was "after sla_due_at has passed without an escalation") — retrievals.py:32-39.
- §3.9 — insert — ambiguity — request lands in RECEIVED with `fee_cents` 0 and `denial_reason` null — verification.py:53-62.
- §3.9 — insert — ambiguity — revoke evaluates ACTIVE-state (409) before ownership (403 `ERR_UNAUTHORIZED`) — consent.py:99-105.
- §3.9 — insert — ambiguity — FERPA covering grant must be recorded against the subject student; scope covering order pinned `ENROLLMENT_ONLY < DEGREE_ONLY < FULL_RECORD` — verification.py:133-145, services.py:87.
- §3.10 — insert — ambiguity — segregation check runs before state checks on both approve and reject — reissues.py:101,159.
- §3.10 — insert — ambiguity — replacement inherits `student_id`/`order_kind`/`rush_requested`/`submitted_at`, starts `rush_qualified` false with both fees 0; copied lines carry `recipient_id`/`delivery_kind`/`quantity`/`unit_price_cents`/`archived_retrieval_id` with null `tracking_ref` — reissues.py:114-144.
- §3.11 — revise — mismatch — lock re-runs the sweep against current state before freezing; non-OPEN lock → `ERR_INVALID_STATE` 409 (was `ERR_BATCH_ALREADY_LOCKED`; no membership-mutation endpoint exists) — clearinghouse.py:62-74.
- §3.11 — insert — ambiguity — mark-failed reverts swept REPORTED verification requests to APPROVED — clearinghouse.py:114-123.
- §4 — revise — mismatch — GET `/registrar/holds/{id}` role list gains `Student` — holds.py:28-35,137-139.
- §4 — revise — mismatch — PATCH `/registrar/recipients/{id}` description gains display name — recipients.py:104-109.

The §5 error catalogue was left intact (pure ID→status listing); §3 prose now explicitly notes `ERR_CAPTURE_EXCEEDS_AUTHORIZED` is never raised by capture, and `ERR_BATCH_ALREADY_LOCKED`/`ERR_NO_BLOCKING_HOLD` no longer have behavioral claims attached.

PIPELINE COMPLETE — all 9 steps done. Final state: 72/72 tests pass across 8 parallel stability rounds.
