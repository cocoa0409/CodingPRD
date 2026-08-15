# Worklog — task_1516_rent_collection_delinquency_enforcement

## Step 1: Create Task Directory — 2026-08-13T18:07:00.000Z

Task directory `tasks/task_1516_rent_collection_delinquency_enforcement/` and `workspace/` were pre-created and pre-assigned by the pipeline launcher; Step 1 treated as DONE per invocation instructions. Difficulty directive from user: "Generate task hard than expert level!" — forwarded to scaffold generation.

## Step 2: Generate Scaffold — 2026-08-13T19:40:00.000Z

All three artifacts are written and the lint verdict is clean. Summary:

## Files produced
- `/home/ubuntu/github/CodingPRD/tasks/task_1516_rent_collection_delinquency_enforcement/SCAFFOLD.yaml` — §1.0–§1.7 only (no difficulty/corner keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_1516_rent_collection_delinquency_enforcement/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — `scaffold_difficulty_design:` only
- `/home/ubuntu/github/CodingPRD/tasks/task_1516_rent_collection_delinquency_enforcement/SCAFFOLD_CORNER_DESIGN.yaml` — `scaffold_corner_design:` only

## Counts
- Entities: **10** (Property, Tenant, Lease, LedgerCharge, Payment, PaymentAllocation, DelinquencyNotice, PaymentPlan, Dispute, CollectionsReferral)
- State machines: **7** (three cyclic: Payment POSTED→RETURNED→POSTED, Dispute reopen loop capped at 1, Referral re-referral; PaymentPlan/LedgerCharge branching; Lease linear with hard terminal)
- Calculations: **8** (late-fee with provisional/final variants, waterfall with FEES_FIRST/RENT_FIRST variants, setup-fee pre-evaluation order, installment floor+remainder split, waiver monthly cap, move-out reconciliation with forward/chronological variants, notice demand, installment evaluation)
- Validations: **18** priority rows (auth → existence → OCC → state → safety/SoD → referential → temporal → constraint → fiscal)
- Endpoints: **31** (within Expert cap of 32), including `POST /api/delinquency-runs` (ops checkpoint) and `POST /api/_clock/set_current_utc` (default 2026-08-01T00:00:00Z)
- Errors: **30** (exactly at Expert cap); Roles: **4** (PropertyManager/LeasingAgent/SystemOps opaque, Tenant entity_backed); Concurrency rules: **2** (OCC on Lease.version for notice/plan create-with-supersede)
- §1.8 instances: **26** (dual_variant 3, combinatorial 3 — one per mode (a)/(b)/(c), non_linear_sm 3, transitive_cascade 3, priority_pair 2, boundary 4, cross_entity 3, temporal_overlap 2, compensating_invariant 3)
- §1.9 instances: **53 active + 4 exclusion stubs** across all nine guide sections

## Lint verdict (verbatim)
```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
(752 calls scanned; additionally verified programmatically: zero unbound `${var}` placeholders, zero unresolvable `grounds:`, all 30 error ids both referenced and test-covered, all instance names unique across both files.)

## Design decisions worth flagging
- **Parameterized transition endpoints** (`POST /{entity}/{id}/transition {action: ...}`) were used to stay inside the 32-endpoint Expert ceiling while preserving all lifecycle depth; per-entity invalid-transition errors keep failures domain-specific.
- **PaymentAllocation is an append-only signed ledger** (`common_fields: false`, APPLY/REVERSE rows instead of mutation) — this makes the NSF compensating invariants (lease identity, per-payment conservation) cleanly testable.
- **Proration lives only in the chronological calculation variant**, not in move-out mutations, so the forward-vs-chronological divergence (400000 vs 122581 on the pinned fixture) is structural rather than data-dependent; NSF-after-move-out retroactively creating a PENDING referral at the prorated 122581 is the deepest corner instance.
- **Rule 6 endpoints were deliberately disambiguated**: the late-fee cap-clamp boundary was moved from the sweep to `POST /api/notices` (provisional demand) so all four boundary instances sit on distinct endpoints per §0.5.
- Segregation-of-duties is enforced by `created_by_user_id`/`drafted_by_user_id` vs `X-User-ID` comparisons (waivers, plan approvals), with fixtures pinning `pm-1`/`pm-2` opaque ids.
- Two targeted edits were made mid-design to keep self-consistency: validation p10 was pointed at `ERR_INVALID_REQUEST` (the `ERR_INVALID_DATE_RANGE` code was dropped to hold the 30-error cap), and lease transition misuse was pinned to domain errors (`MOVE_OUT` from ENDED → `ERR_LEASE_ALREADY_ENDED`, `ACTIVATE` from non-DRAFT → `ERR_INVALID_REQUEST`).

## Step 3: Copy Shared Files — 2026-08-13T19:41:00.000Z

Copied ./INSTRUCTION.md → tasks/task_1516_rent_collection_delinquency_enforcement/workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-08-13T19:55:00.000Z

All checks pass. The PRD is complete and verified.

## Summary

**Output**: `/home/ubuntu/github/CodingPRD/tasks/task_1516_rent_collection_delinquency_enforcement/workspace/PRD.md` — 302 lines.

### Section structure

- **§1 Introduction** — 2 paragraphs (business-context angle: ledger-as-system-of-record + jurisdictional enforcement; role segregation and cascade/OCC motivation).
- **§2 Global Specifications** (10 subsections): 2.1 RBAC (headers, 4 roles, per-role `identity` prose — Tenant entity-backed, the other three opaque); 2.2 API Response Structure (**emitted byte-for-byte verbatim** from `section-2.2-response-structure.md`, verified programmatically); 2.3 Pagination; 2.4 Money/Dates/Logical Clock (integer cents, round-half-up rule points, clock start 2026-08-01T00:00:00Z); 2.5 Common Resource Properties (incl. PaymentAllocation exception: only `id`+`created_at`, no `updated_at`/`version`); 2.6 Property-Governed Policy Constants; 2.7 Ledger Integrity & Cross-Entity Cascades (Cascade A/B/C summaries + universal version/`updated_at` rule); 2.8 OCC (`expected_lease_version`, `ERR_STALE_VERSION`/412, notice + plan creation only); 2.9 Validation Order (all 18 scaffold priorities as an ordered first-failure-wins pipeline with per-stage error ids); 2.10 Nested Resource Retrieval.
- **§3 Business Logic** (9 subsections, organized by business-process timeline): 3.1 Portfolio Setup → 3.2 Lease Ledger & Balance Reads → 3.3 Payments & Posting Waterfall → 3.4 Returns/NSF/Re-presentment → 3.5 Waivers & Monthly Cap → 3.6 Late Fees & Delinquency Sweep → 3.7 Pay-or-Quit Notices → 3.8 Payment Plans → 3.9 Disputes, Move-Out & Collections.
- **§4 Endpoint Definitions** — 31-row table, 4 columns only.
- **§5 Error Code Catalogue** — 30-row table, 2 columns only.

### Coverage notes / scaffold mapping

- Entities → 3.1 (Property/Tenant/Lease), 3.2 (LedgerCharge + ledger read), 3.3 (Payment/PaymentAllocation), 3.7 (DelinquencyNotice), 3.8 (PaymentPlan), 3.9 (Dispute/CollectionsReferral).
- All 7 state machines fully expressed as prose state-pairs, including misused-transition mappings (MOVE_OUT from DRAFT/ENDED, ACTIVATE from non-DRAFT) and the cyclic machines (payment re-presentment, dispute reopen-once, referral re-referral).
- All 8 calculations expressed as precise prose formulas: late-fee (both final and provisional variants), waterfall (both `FEES_FIRST`/`RENT_FIRST` variants with equal density), pinned setup-fee evaluation order, floor-then-remainder installment split, waiver monthly cap, both move-out reconciliation variants (incl. proration day-counting and the not-ENDED no-proration rule), live/frozen notice demand, and installment evaluation.
- Deliberate compressions: per-transition `version`+1/`updated_at` side effects are stated once as a universal rule in §2.7 rather than repeated per transition; null defaults for lifecycle fields are grouped into one sentence per entity subsection. No rules omitted.

### Hard-contract reports

```
Field coverage check:
- entities[].fields: 76 required, 76 present, 0 missing
- endpoints[].request_body: 58 required, 58 present, 0 missing
- endpoints[].query_params: 10 required, 10 present, 0 missing
- (also verified: 15 output-side identifiers — ledger read, sweep counts, current_utc, sequence_number — all present)
Status: PASS

Rule coverage check:
- validations[] with priority: 18 checked, 18 expressed in prose (§2.9 ordered pipeline + in-workflow restatements), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (endpoint capability + expected_lease_version + ERR_STALE_VERSION/412 all named; no race framing), 0 missing
- state_machines[].transitions: 34 checked, 34 fully expressed, 0 missing
- calculations[]: 8 checked, 8 fully expressed, 0 missing
- validations[] conditions: 18 checked, 18 matchable to error_id in prose (all 30 error ids appear in §2/§3), 0 missing
- endpoints[].side_effects / applies_to: all expressed in workflow narratives, 0 missing
- entities[].fields[] structured content: defaults/initials (incl. null-until-set lifecycle fields) reconstructible from prose, 0 missing
- sibling-branch symmetry: 8 groups checked (waterfall variants, late-fee variants, balance variants, WAIVED/VOID/CURED/EXPIRED sibling transitions, RECALLED→REFERRED gates, REOPENED→RESOLVED_*), all equal density, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 499
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0 (the payment posting action is referred to as "the posting transition"/state-pair `PENDING` → `POSTED`, never backticked `POST`)
- method+path combined tokens: 0
Status: PASS
```

The two withheld files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were not opened, grepped, or referenced at any point.

## Step 5: Generate Unit Tests — 2026-08-13T20:45:00.000Z

Generation complete. Final summary:

## Summary

**Task:** `task_1516_rent_collection_delinquency_enforcement` — full test generation per the prd-bench-unit-test-generator skill.

### Coverage counts
- **Queue A (§1.8 difficulty):** 26/26 instances covered, each with exactly **≥2 tests** (53 difficulty-tagged tests total).
- **Queue B (§1.9 corner):** 53/53 non-stub instances covered, each with **≥1 test** (53 corner-tagged tests, one per instance).
- **Stubs:** 4 `excluded_because:` stubs NOT translated; all 4 cross-references verified to resolve to real difficulty instances (`late_fee_formula_golden_value_covered`, `waterfall_golden_split_covered`, `ledger_read_variants_covered`, `grace_boundary_covered`).
- **Total:** 106 tests emitted (105 tagged + 1 supplementary `test_moveout_zero_balance_creates_no_referral` also tagged to the move-out instance — all 105 collected tests carry exactly one Design tag; the audit counted 105 tag occurrences because each test has exactly one).

Correction: audit shows 105 collected tests, 105 Design tags, all resolving to real instances.

### Skipped instances
**None.** Every non-stub instance passed the PRD-first two-condition filter. One deliberate adjudication: for `payment_creation_gated_by_lease_state` (whose recipe asserts `ERR_LEASE_NOT_ACTIVE` on payment *creation* against a DRAFT lease), the PRD explicitly states the opposite ("a lease still in `DRAFT` may record a payment, but that payment cannot be posted until the lease is active"). Per PRD-first, the tests assert the PRD's actual rule — creation succeeds in DRAFT, posting fails with `ERR_LEASE_NOT_ACTIVE`, and post-move-out creation fails with `ERR_LEASE_ALREADY_ENDED`.

### Stage-2 self-checks (all green)
- Design-tag audit: every difficulty instance ≥2 tests, every corner non-stub ≥1, zero bad tags, zero untagged tests, zero dual tags.
- PRD-citation pass: 127 quoted citation spans across all test docstrings — every one contains a ≥8-word window surviving a literal (whitespace-normalized) grep of PRD.md.
- Error-id pass: all 30 asserted `ApiErrorId` values named in PRD prose (not just the §5 table).
- No `pytest.mark.skip` / `skipif` / `xfail` anywhere.
- `python -m pytest --collect-only`: **105 tests collected**, no import errors; all files compile.

### Files generated
- `test_helpers/`: `__init__.py`, `types.py` (11 entity TypedDicts, 18 enums; PaymentAllocation correctly omits `updated_at`/`version`), `api_client.py` (27 endpoint methods), `api_errors.py` (30 errors + HTTP map registered via `set_error_http_status_map`), `assertions.py`, `factories.py`, `constants.py`, `test_users.py` (shared constants + per-instance builders incl. entity-backed `make_tenant_headers`), `fixtures.py` (composite helpers: `setup_property_tenant_lease`, `add_charge`, `create_notice`, `create_plan`, `approve_plan`, `record_and_post_payment`, `move_out_lease`, `setup_ended_lease_with_referral`, `file_dispute`/`resolve_dispute`/`reopen_dispute`, `set_clock`, `run_sweep`, list readers).
- `test_suite/`: `conftest.py` + 12 test files (`test_01_entities_and_defaults` … `test_12_rbac_and_consistency`), organized by domain concern and numbered simple→complex.

## Step 6: Generate Implementation — 2026-08-13T21:10:00.000Z

All done — 105/105 tests pass. Here is the final report.

## Summary

**Result: 105/105 tests pass** under `prd-bench-local-run --isolation per-test-server` (server killed and re-launched via `start.sh` before every test; results: `total=105, passed=105, failed=0, errors=0`). NOTE: this was the generator's own single-round confirmation run, NOT the official Step 7 8-round parallel stability sweep.

### File list — `workspace/implementation/`
- `start.sh` (executable; guarded `pip install` no-op when Flask is present; `exec python3 app.py` in foreground)
- `requirements.txt` (`flask>=3.0`)
- `app.py` — Flask entry, blueprint registration under `/api`, error handlers (ApiError → envelope; 404/405 → `ERR_NOT_FOUND` envelope), binds `0.0.0.0:$PORT` (default 10000)
- `db.py` — in-memory dict stores (all empty at boot, zero seeding), logical clock starting at exactly `2026-08-01T00:00:00Z`, logical-clock-derived monotonic millisecond timestamps for `created_at`/`updated_at`/envelope timestamps
- `errors.py` — all 30 PRD §5 error IDs with HTTP statuses
- `response.py` — success/error envelopes (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`; pagination fields in `meta`)
- `middleware.py` — `X-User-ID`/`X-User-Role` auth (tier 1), RBAC + Tenant ownership (tier 2)
- `validators.py` — body shape checks, date/instant parsing, `limit`/`offset` pagination (default 10, 1..100), `created_at`-ascending listing
- `serializers.py` — per-entity field whitelists (PaymentAllocation exposes only `id`/`created_at` + ledger fields; internal `_`-prefixed keys never leak)
- `routes/`: `properties.py`, `tenants.py`, `leases.py`, `charges.py`, `payments.py`, `allocations.py`, `notices.py`, `plans.py`, `disputes.py`, `referrals.py`, `ops.py`
- `services/calc.py` — late-fee (FLAT / PERCENT_PLUS_DAILY, cap clamp), waterfall (FEES_FIRST/RENT_FIRST, due_date then created_at), proration and both move-out balance variants, notice demand (live provisional fees), installment floor-then-remainder split, monthly waiver cap; all money in exact integer cents (`round_half_up` via integer arithmetic, no floats)
- `services/workflows.py` — Cascades A (NSF return) / B (move-out) / C (dispute adjustment), charge/notice/referral recomputes, the idempotent delinquency sweep

### Endpoints implemented: 31/31 (every row of the PRD §4 / scaffold §1.5 table — no extras)

### PRD ambiguities resolved at generation time
1. **`received_date` future ceiling (the one real conflict):** PRD 3.3/2.9-rule-10 say a supplied `received_date` "must not lie in the future" under the logical clock, but two authoritative suite tests (`test_03` waterfall pair) record `received_date` 2026-08-03/2026-08-05 under the default 2026-08-01 clock and expect success; no test asserts the rejection. I chose the test-suite behavior: format-validated, no future check (noted in a code comment in `routes/payments.py`).
2. **RETURN reversal scope:** "every APPLY allocation the payment ever created" is implemented as "the current posting run's APPLYs" — the literal reading double-reverses after a re-presentment and breaks conservation.
3. **Notice demand freeze:** recomputed only on the four PRD-listed covered-charge change events; clock advancement alone does not recompute a DRAFT demand, and ISSUE freezes the stored value without a final recompute.
4. **Auto-recall of PENDING referrals:** PRD §3.9's unconditional sentence ("when a recomputation drives a PENDING referral's balance below the threshold") was applied to all recompute paths (waiver + dispute), not only Cascade C; a referral created below threshold at move-out stays PENDING until a recompute changes its balance (matches the pinned 9999-threshold test).
5. **NSF fee with omitted/zero `nsf_fee_cents`:** no `NSF_FEE` charge is created (the fee is an optional request; `min(0, cap)` would mint a degenerate 0-amount charge).
6. **PLAN_SETUP_FEE period:** set to `first_installment_date` for both period dates (PRD pins only its due date and `PLAN` source; mirrors the NSF fee's "period equals its date" rule).
7. **Tenant list reads:** single-resource and lease-pathed reads enforce ownership with `ERR_UNAUTHORIZED`; global list endpoints (`/leases`, `/payments`, `/disputes`, `/allocations`) are force-scoped to the caller's own lease graph.
8. **Ledger-read totals:** computed over non-VOID charges only, preserving the `charged == waived + outstanding + applied_net` identity through voids.
9. **Plan activation date:** stored as an internal `_activated_date` (never serialized) to drive the sweep's "posted_date >= activation" coverage filter.
10. **Duplicate tenant email:** rejected with `ERR_INVALID_REQUEST` (no dedicated error ID exists in the catalog).

### Test-suite repairs (not implementation changes)
Two test files had generation defects — `NameError` from missing imports, failing before any assertion: added `record_and_post_payment` + `return_payment` to `test_suite/test_06_payment_plans.py` imports and `create_tenant_payload` + `resolve_dispute` to `test_suite/test_12_rbac_and_consistency.py` imports. No assertions or expected values were altered.

### Smoke-boot confirmation
Manual `bash start.sh` boots were verified twice on a custom `PORT` (fresh process, HTTP-ready in ~2s, correct envelope and 401 behavior), and the full `per-test-server` run re-invoked `start.sh` 105 times with clean, state-free boots each time.

## Step 7: Run Tests and Iterate — 2026-08-13T21:25:00.000Z

**Summary**

- **Iterations run:** 1 — the official 8-round parallel stability sweep (all 8 rounds launched concurrently under `--isolation per-test-server`, joined with `wait`; every round ran to completion).
- **Result:** All 8 rounds passed 105/105. Union of failing tests across rounds 1–8: **NONE**. Verified directly from `results.1.json` … `results.8.json` (`passed == total == 105` in every round; every per-test entry has `status: passed`).
- **Tests deleted:** none.
- **Fixes applied to `test_helpers/`:** none this iteration. (The two pre-existing generation defects — missing imports of `record_and_post_payment`/`return_payment` in `test_suite/test_06_payment_plans.py` and `create_tenant_payload`/`resolve_dispute` in `test_suite/test_12_rbac_and_consistency.py` — had already been repaired by the implementation generator before this sweep; I confirmed the current tree is consistent and made no changes.)
- **Fixes applied to `implementation/`:** none — the implementation at `/home/ubuntu/github/CodingPRD/tasks/task_1516_rent_collection_delinquency_enforcement/workspace/implementation/` passed the full suite in all 8 parallel rounds with no flakiness signal.

The task is stable: a single clean 8-round sweep with zero failures, so no diagnostic-protocol steps were triggered. Exiting per protocol.

## Step 8: Finalize PRD — SKIPPED — 2026-08-13T21:26:00.000Z

Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes — zero iterations beyond the baseline. Per the skip condition, `PRD.md` already determined every behavior the implementation exhibits at the Step-7 site level; no `PRD_FINALIZED.md` is produced. (Note: Step 6's generation-time ambiguity resolutions are precisely Step 9's input domain, so Step 9 runs from `PRD.md` directly.)

## Step 9: Complete PRD — 2026-08-13T21:55:00.000Z

All edits verified. The task is complete. Here is the summary.

## Summary

**Produced:** `/home/ubuntu/github/CodingPRD/tasks/task_1516_rent_collection_delinquency_enforcement/workspace/PRD_COMPLETED.md`

**Size:** PRD.md = 301 lines / 59,921 chars; PRD_COMPLETED.md = 301 lines / 63,653 chars; char-delta **+3,732** (line count unchanged — all changes are inline inserts/revisions; 22 lines touched).

**Counts:** 20 ambiguity-pins, 7 mismatch-revisions (27 distinct behavioral changes across the 22 edited lines).

### Changes

- **§2.1** — insert — ambiguity — Tenant callers' list endpoints are force-scoped to their own lease graph before query filters (leases by `primary_tenant_id`; payments/disputes by `tenant_id`; allocations via own payments) — routes/leases.py:34-36,105-106; routes/payments.py:105-106; routes/disputes.py:94-95; routes/allocations.py:38-42.
- **§2.3** — revise — ambiguity — `total_count` = full filtered population; `has_more` true iff `offset` + returned items < `total_count` — implementation/response.py:33; validators.py:197-208.
- **§2.4** — insert — ambiguity — all server-emitted timestamps (`created_at`, `updated_at`, `api_request_timestamp`) render from the logical clock, kept strictly increasing at ms resolution — implementation/db.py:64-78.
- **§2.4** — revise — ambiguity — clock-set adopts any supplied instant (forward or backward) and echoes the supplied value back as `current_utc` — routes/ops.py:25-34; db.py:55-57.
- **§2.4** — revise — mismatch — dropped "received-date ceilings" from the logical-clock rule enumeration (no such rule exists in impl) — routes/payments.py:66-69.
- **§2.5** — insert — ambiguity — `version` starts at 1 on creation — db.py:81-87.
- **§2.7** — revise — mismatch — Cascade A summary: reversal scope = allocations of the current posting run; fee charge created only when requested and capped amount > 0 — services/workflows.py:146,188-200,209-213.
- **§2.9 tier 4** — insert — ambiguity — ownership checks depending on a body-referenced lease are evaluated after the reference resolves, so a nonexistent body reference yields `ERR_NOT_FOUND` even when ownership would also fail — routes/payments.py:48-58; routes/plans.py:44-58; routes/disputes.py:41-55.
- **§2.9 tier 10** — revise — mismatch — removed the `received_date` future-ceiling (format-validated only); `served_date`/`first_installment_date` explicitly deferred to tiers 11/12 with their dedicated errors — routes/payments.py:40,66-69; routes/notices.py:186-195; routes/plans.py:94-98.
- **§2.9 tier 18** — insert — ambiguity — each field's shape is validated at the point the workflow first reads it (so early-read shape failures precede later gates; late-read ones follow passed gates) — validators.py:14-163; routes/payments.py:35-40 vs routes/leases.py:166.
- **§3.1** — insert — ambiguity — duplicate tenant email rejected with `ERR_INVALID_REQUEST` — routes/tenants.py:25-30.
- **§3.2** — insert — ambiguity — system-charge period enumeration extended: plan setup fee carries the first installment date as due date and both period dates — routes/plans.py:137-143.
- **§3.2** — revise — ambiguity — ledger components (`total_charged/waived/applied_net/outstanding`, `open_charge_count`) computed over non-`VOID` charges; open count over `OPEN`/`PARTIALLY_PAID` — routes/leases.py:182-191.
- **§3.2** — revise — mismatch — removed "a single charge may be read by any role" (no `GET /api/charges/{id}` exists in impl, §4 table, or test client) — routes/charges.py (only create/list/waive routes exist).
- **§3.3** — revise — mismatch — `received_date` is format-validated only; no future-date ceiling — routes/payments.py:40,66-69 (impl comment confirms deliberate non-enforcement).
- **§3.4** — revise — ambiguity — `reason_code` optional (preserved when supplied); supplied `nsf_fee_cents` recorded on the payment verbatim before capping — routes/payments.py:162-163; services/workflows.py:182-184.
- **§3.4** — revise — mismatch — RETURN reverses only the current posting run's `APPLY` allocations (`_current_run` overwritten per posting); each `REVERSE` carries the reversed `APPLY`'s `allocation_order` — services/workflows.py:146,188-200.
- **§3.4** — revise — ambiguity — no `NSF_FEE` charge when `nsf_fee_cents` is omitted or the capped amount computes to zero — services/workflows.py:209-213.
- **§3.7** — insert — ambiguity — notice `charge_ids` must be a non-empty ordered list — validators.py:142-152.
- **§3.7** — revise — ambiguity — draft demand recomputed on exactly five events (allocation, reversal, waiver, dispute adjustment, plus the sweep's late-fee assessment for a covered rent charge's period which drops the provisional component); clock advancement alone does not recompute — services/workflows.py:50-58,311.
- **§3.7** — insert — mismatch — ISSUE evaluates the notice transition precondition before the lease lifecycle gate (non-`DRAFT` notice + ended lease → `ERR_NOTICE_INVALID_TRANSITION`) — routes/notices.py:135-147.
- **§3.8** — revise — ambiguity — plan `charge_ids` a non-empty snapshot; an element not `OPEN`/`PARTIALLY_PAID` rejected as `ERR_INVALID_REQUEST` — routes/plans.py:40,82-86.
- **§3.8** — insert — ambiguity — `PLAN_SETUP_FEE` charge carries `first_installment_date` as both `period_start_date` and `period_end_date` — routes/plans.py:137-143.
- **§3.8** — revise — ambiguity — installment due dates computed as `first_installment_date` + (sequence_number − 1) calendar months with day-of-month clamped to the target month (not compounded from the previous installment) — services/calc.py:18-24,158-175.
- **§3.8** — insert — ambiguity — approval stamps an internal activation date (current date) read only by the sweep; never exposed on the plan's serialized form — routes/plans.py:232; serializers.py:50-55,96-107.
- **§3.9** — revise — ambiguity — `agency_name` optional at REFER (recorded when supplied); `recall_reason` optional at RECALL — routes/referrals.py:56,78.
- **§3.9** — revise — ambiguity — system auto-recall (`BALANCE_RESOLVED`) applies on every PENDING-referral recompute path (posting, reversal, waiver, dispute adjustment), not only Cascade C — services/workflows.py:61-76 (via `cascade_charge_changed`, `return_payment`, `apply_dispute_adjustment`).

All nine known generation-time ambiguity resolutions listed in the task were verified against the code and pinned. Notable extra finding beyond the list: the PRD §3.2 prose asserted a single-charge read ("a single charge may be read by any role") for which no endpoint exists in the §4 table, the implementation, or the test client — removed as a mismatch.
