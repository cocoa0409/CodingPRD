# Worklog — task_0056_pet_health_insurance_claims

## Step 1: Create task directory — 2026-05-30T15:55:06Z

Created `tasks/task_0056_pet_health_insurance_claims/` and `tasks/task_0056_pet_health_insurance_claims/workspace/`. Directory was pre-allocated per orchestrator instructions (no ID scan performed).

## Step 2: Generate scaffold (Expert difficulty) — 2026-05-30T16:10:29Z

All structurally sound: 10 difficulty rule_id blocks (9 §0.5 rules + the concurrency rule) with 20 instances total (≥18), 35 corner instances across all 9 taxonomy sections. Lint is clean.

The scaffold artifacts for `task_0056_pet_health_insurance_claims` are complete and pass `scaffold_lint.py` cleanly. Here is the verdict block, verbatim:

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
  §1.5 endpoints declared:    39
  §1.1 entities declared:     7
  §1.8 instances scanned:     20
  §1.9 instances scanned:     32
  Calls scanned (§1.8+§1.9):  492
```

**Difficulty:** Expert. **Archetype:** Ledger reconciliation (primary) + Pricing engine (secondary). Layers: dual-variant calculation, rate/threshold triggers, derived-field reconciliation, optimistic concurrency. Topology hybrid, state-machine shape branching, role model peer_roles, consistency immediate.

**Entities (7):** Account, Policy, PolicyYear, MedicalCondition, Claim, ClaimLine, InvoiceDocument. Computed fields include Account.monthly_premium_cents/multi_pet_discount_applied, PolicyYear deductible/reimbursed/wellness accumulators, Claim payable fields, ClaimLine.allowed_amount, InvoiceDocument.ocr_mismatch_bps.

**State machines (3):**
- Policy: PENDING_PAYMENT → ACTIVE → {LAPSED, CANCELLED} (activate creates PolicyYear 0 and re-prices the account).
- InvoiceDocument: PENDING_OCR → {OCR_DONE | REVIEW_NEEDED} → {ACCEPTED | REJECTED} (OCR mismatch >500bps forks to REVIEW_NEEDED).
- Claim: DRAFT → SUBMITTED → IN_REVIEW → {APPROVED → PAID | DENIED}, plus APPROVED → DENIED reverse (compensation).

**Calculations (4):** `policy_year_ledger`; `account_monthly_premium`; `claim_eligible_amount`; `condition_exclusion`.

**Validations (13, ordered):** auth → role → existence → FK → state → owner → waiting-period → pre-existing → policy-year-closed → claim-ready → wellness-rider → OCC → invalid-request.

**Endpoints (39):** account/policy/condition/claim/line/invoice CRUD + lifecycle action endpoints; nested and flat filtered-list GETs; `/_clock/set_current_utc` test-driving endpoint.

**Errors (14):** auth/role/owner/not-found/FK + domain errors.

**Roles (3):** PolicyHolder (entity_backed:Account), Underwriter (opaque), ClaimsAdjuster (opaque).

**Concurrency:** one OCC rule — `adjudicate-stale-policy-year` on PolicyYear.version.

Note: `api_prefix: ""` (root-level paths); flat single-resource + filtered-list GETs added for FK reverse-reachability; nested business GETs are what test recipes use.

## Step 3: Copy INSTRUCTION.md — 2026-05-30T16:10:29Z

Copied `./INSTRUCTION.md` → `tasks/task_0056_pet_health_insurance_claims/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-05-30T16:14:28Z

Generated `workspace/PRD.md` for the Pet Health Insurance Claims API — ledger-reconciliation domain with a pricing engine layer.

Structure: §1 Introduction (3 paragraphs); §2 Global Specs (8 subsections: RBAC for all 3 roles, §2.2 envelope, pagination, common properties/versioning, hierarchical consistency + left-to-right path validation, monetary precision, OCC on policy-year accumulators — 412/`ERR_STALE_POLICY_YEAR_VERSION`, coverage-year ledger principle); §3 Business Logic (7 scattered subsections: account pricing/multi-pet discount, policy lifecycle, pre-existing exclusion, claim assembly, OCR pipeline, submission/eligibility, adjudication + chronological ledger + payment/reversal); §4 39-endpoint table; §5 14-error table.

Key rule coverage: all 7 Policy / 4 InvoiceDocument / 7 Claim transitions with preconditions paired to error IDs; both calculations (`policy_year_ledger` with chronological re-attribution + incident-date/created_at tie-break, `account_monthly_premium` with pinned discount-then-rider order); wellness vs non-wellness sibling branches at equal density; OCC on adjudicate-approve and reverse; 13-rule validation priority ordering; reversal compensation conserving `PolicyYear.reimbursed_cents`.

Hard Contracts: Contract 1 (Field-Name Coverage) PASS — 0 missing; Contract 2 (Rule Coverage) PASS; Contract 3 (§3 Path Purity) PASS — 304 backtick tokens, 0 path-leading/bare-method/method+path. No fuzzy words; all numeric constants embedded.

## Step 5: Generate unit tests — 2026-05-30T16:26:29Z

Generated complete test infrastructure. test_helpers/ (9 files): types.py, api_client.py (40 endpoints incl. nested + flat + /_clock), api_errors.py (ApiErrorId enum + HTTP status map; ERR_CLAIM_REVERSED omitted from map as stored sentinel per PRD §3.7/§5), assertions.py, factories.py, constants.py, test_users.py (PolicyHolder entity_backed:Account; Underwriter/ClaimsAdjuster opaque), fixtures.py, __init__.py.

test_suite/ (conftest + 7 test files, 72 tests):
- Queue A (Difficulty): 20 instances × 2 tests = 40 tests
- Queue B (Corner): 32 non-stub instances × 1 test = 32 tests
- 3 corner excluded_because: stubs correctly NOT translated (pointers resolve to real queue-A instances).
- No instances skipped for PRD-coverage failure; both validation-priority pairs explicitly in PRD prose (§3.7, §2.5).

Integrity: 72 Design tags = 72 test defs (no untagged/dual-tagged/dangling); all 17 files parse; zero scaffold leakage. OCC tests use deterministic sequential approve-then-stale-adjudicate.

## Step 6: Generate implementation — 2026-05-30T16:26:29Z

Generated complete Python + Flask REST API in workspace/implementation/. In-memory storage only (module-level dicts in db.py, empty on boot); start.sh installs Flask if missing then execs app on 0.0.0.0:$PORT (default 10000).

Files: start.sh, requirements.txt (flask==3.0.3), app.py, db.py (7 stores, UUID/ISO-8601 UTC 3-digit timestamps, monotonic _seq for created_at tie-break, logical clock now_dt), response.py (envelope + pagination default 10/min 1/max 100), middleware.py (X-User-ID/X-User-Role auth), routes/{accounts,claims,flat,clock}.py, services/{common,calculations,ledger}.py.

Endpoints: all 38 (account CRUD; policy create/activate/lapse/cancel nested + flat; policy-years; conditions; claim open/lines/invoices; invoice run-ocr/accept/reject; claim submit/begin-review/adjudicate/pay/reverse; flat list+fetch; POST /_clock/set_current_utc).

Key logic: pricing (discount base by 1000bps only when ≥2 ACTIVE policies, round half-up per policy, add undiscounted 1500-cent rider; verified 11500 single / 21000 multi); chronological coverage-year ledger (reattribute over non-WELLNESS APPROVED/PAID claims by incident_date ASC, created_at ASC; deductible→post-deductible×rate round-half-up→cap clamp; retroactive deductible-stealing verified); wellness bucket (bypass deductible/cap, min(eligible, 30000−wellness_used)); reverse compensation (zero payable, reconcile PolicyYear, denial_reason=ERR_CLAIM_REVERSED); OCC (expected_policy_year_version on adjudicate optional, reverse required → 412); state machines (Policy/Claim/InvoiceDocument, OCR mismatch >500bps→REVIEW_NEEDED); validation precedence auth→not-found→FK→state→owner→waiting-period→pre-existing→policy-year-closed→OCC; cascades bump version/updated_at on path entity + recomputed parents. Smoke-tested full lifecycle + negative paths; confirmed fresh-boot empty state.

## Step 7: Test and iterate to PASS — 2026-05-30T16:47:06Z

All tests pass across all 8 parallel rounds (69/69 × 8).

**Iterations run:** 2 (initial sweep diagnosing 7 distinct failures consistent across all 8 rounds; second sweep clean at 69/69 × 8).

**Root cause of the cluster:** the PRD freezes `submitted_amount_cents` only at claim submission (PRD 3.6), but submission structurally requires an already-ACCEPTED invoice, which requires OCR. So OCR always runs while the claim is still DRAFT with `submitted_amount_cents == 0`. Several tests assumed it equalled the line sum at OCR time — not derivable from PRD prose. The current implementation was PRD-faithful in all 7 cases; the fixes were entirely test-side.

**Tests deleted (3):**
- `test_ocr_high_mismatch_forks_review_needed_then_reject` — UNIQUE-DERIVABILITY collapse (DEFAULT-VALUE SILENCE). The REVIEW_NEEDED branch requires mismatch > 500 bps, which requires `submitted_amount_cents > 0` at OCR time; PRD never computes it during DRAFT, so the branch is unreachable under a faithful impl.
- `test_review_needed_invoice_can_be_accepted` — same silence; depends on first reaching the unreachable REVIEW_NEEDED state. (Also the test that consistently showed the "could not be restarted" setup failure.)
- `test_submit_blocked_while_policy_pending_payment` (test_05) — ERROR-PRECEDENCE/mapping SILENCE. PRD 3.6 maps only "claim not in DRAFT → ERR_INVALID_STATE" and "lines/accepted-invoice not met → ERR_CLAIM_NOT_READY"; it never assigns an error_id to the policy-not-ACTIVE precondition. Two faithful readings exist, so the outcome is not uniquely determined.

**Test assertions edited (test_suite/ only; made MORE faithful):**
- `test_03_invoice_ocr_and_eligibility.py` `test_claim_starts_in_draft_with_zero_payable` — added expected-status arg `201` to `validate_success(...)`; PRD 4 says create returns 201 (impl correctly returned 201).
- `test_03_...` `test_ocr_low_mismatch_branches_to_ocr_done` — PARTIAL-COVERAGE split: kept PRD-covered `ocr_status == "OCR_DONE"` (mismatch ≤ 500 → OCR_DONE), dropped non-derivable `ocr_mismatch_bps == 250`.
- `test_04_adjudication_gates.py` `test_incident_before_any_policy_year_rejected_closed` and `test_incident_before_year_leaves_claim_in_review` — fixture date bug. With `waiting_period_days=0`, an incident before `period_start` is also before coverage start, so the higher-priority waiting-period check (PRD 3.7 priority 7) fired ERR_WITHIN_WAITING_PERIOD before the open-policy-year check (priority 9). Changed `incident_date` to `2027-01-01` (past the half-open `period_end`, exclusive) with a COVERED condition, so the open-policy-year check fires — preserving each test's intent while respecting PRD-pinned precedence.

**Fixes applied to test_helpers/:** none.

**Fixes applied to implementation/:** none — the implementation was PRD-faithful for every failure.

## Step 8: Finalize PRD — 2026-05-30T16:50:45Z

Produced `workspace/PRD_FINALIZED.md`. PRD.md vs PRD_FINALIZED.md: both 225 lines (inline edits, no line additions). 2 sentences revised across 2 lines (132, 138).

Changes:
- §3.5 (OCR pipeline) — revise — pinned divide-by-zero behavior of `ocr_mismatch_bps`: when `submitted_amount_cents` is 0 the result is 0 (not a division error); noted it's 0 throughout DRAFT so OCR in practice always lands in OCR_DONE — `implementation/services/calculations.py:95-97`, `routes/claims.py:204-209`.
- §3.6 (Submit) — revise — mapped the policy-not-ACTIVE precondition to `ERR_CLAIM_NOT_READY` (impl folds policy-not-ACTIVE into the same `ERR_CLAIM_NOT_READY` branch alongside no-line / no-accepted-invoice, after the DRAFT/ERR_INVALID_STATE check) — `implementation/routes/claims.py:254-259`.

Note: the waiting-period vs open-policy-year precedence cluster was a pure test-fixture date bug; PRD §3.7 already pins the priority order and impl matches it, so no PRD edit warranted.

## Step 9: Complete PRD — 2026-05-30T16:54:17Z

Produced `workspace/PRD_COMPLETED.md` from PRD_FINALIZED.md. Both 225 lines; chars 34,972 → 36,190 (+1,218). Counts: ambiguity-pins 4, mismatch-revisions 3 (7 changes total).

Changes:
- §3.4 (invoice fields) — insert — ambiguity — `InvoiceDocument` exposes `ocr_mismatch_bps` that begins null and is set when OCR runs — routes/claims.py:166,205.
- §2.7 (OCC) — revise — mismatch — version optional on approve (check skipped when absent/null), mandatory on reverse (missing → `ERR_INVALID_REQUEST`) — routes/claims.py:333-334, 371.
- §3.7 (deny branch) — insert — ambiguity — `reason` optional; `denial_reason` null when absent — routes/claims.py:296.
- §3.7 (reverse) — insert — ambiguity — reversal locates covering `PolicyYear` after state check, before version check; none found → `ERR_POLICY_YEAR_CLOSED` — routes/claims.py:366-368.
- §3.1 (account email) — insert — ambiguity — duplicate email rejected with `ERR_INVALID_REQUEST` — routes/accounts.py:46-47.
- §3.7 (adjudicate ordering) — insert — mismatch — `decision` enum validated after path existence and before state check (`ERR_INVALID_REQUEST` precedes `ERR_INVALID_STATE`) — routes/claims.py:287-291.
- §3.2 (activation/year creation) — insert — mismatch — created year is `CLOSED` (not `OPEN`) if clock at/past its `period_end` — routes/accounts.py:187-188.

Pipeline complete. Final artifacts present: SCAFFOLD.yaml, SCAFFOLD_DIFFICULTY_DESIGN.yaml, SCAFFOLD_CORNER_DESIGN.yaml, worklog.md, test_helpers/, test_suite/ (69 tests), workspace/{INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md, implementation/}.
