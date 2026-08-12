# Worklog — task_1275_check_adjustment_return_item_processing

## Step 1: Create Task Directory — 2026-08-12T15:17:00.000Z

Pre-assigned output folder `tasks/task_1275_check_adjustment_return_item_processing` with `workspace/` subdirectory verified to exist. Step 1 treated as done per invocation instructions; no auto-index scan performed.

## Step 2: Generate Scaffold — 2026-08-12T16:00:30.000Z

Done. All three scaffold artifacts are generated, validated, and lint-clean.

## Deliverables (all under `/home/ubuntu/github/CodingPRD/tasks/task_1275_check_adjustment_return_item_processing/`)

**SCAFFOLD.yaml** (§1.0–§1.7, no design keys) — compliance/audit + ledger-reconciliation archetype, flat topology, cyclic state machines, segregation-of-duties role model:
- **13 entities**: DepositorAccount, ClearingBank, AccountFreeze, CheckItem, HoldDecision, ReturnEvent, AdjustmentCase, AdjustmentClaim, WarrantyClaim, CustomerNotification, FeeAssessment, RecreditRequest, LedgerEntry (append-only, `common_fields: false`)
- **10 state machines** with cycles (CheckItem PRESENTED↔RETURNED re-presentment loop; AdjustmentCase RESOLVED→REOPENED→ASSIGNED; account ACTIVE↔FROZEN auto-freeze on negative balance) plus system sweeps (notification breach → case escalation, hold expiry → auto-release, claim aging → escalation)
- **9 calculations** incl. tiered return-item fee (mode a), per-day-rounded recredit interest (mode b, pinned rounding order), provisional-vs-settled balance and business-vs-calendar claim aging (dual variants on different entity domains)
- **2 OCC concurrency rules** (`account-update-stale-version`, `case-assign-stale-version`) — both pass the serial-observability filter (re-assignment legitimately supersedes)
- **54 endpoints** incl. `POST /bank/ops/run-daily` (ops checkpoint) and `POST /_clock/set_current_utc` (default clock 2026-05-01T00:00:00Z, a Friday — all deadline fixtures verified by executing the business-day math)
- **40 error codes**, 11-priority validation table, 6 roles (Customer is `entity_backed:DepositorAccount`)

**SCAFFOLD_DIFFICULTY_DESIGN.yaml** — 9 rules × 2 instances = 18, each with fully structured `setup_api_calls`/`trigger`/`assert` chains; every formula-derived assert pre-computed to a literal (e.g., fee 3750 vs 4250 tier jump, recredit interest 135 vs the 133 an aggregate-rounding implementation would produce, aging 10 calendar vs 6 business days).

**SCAFFOLD_CORNER_DESIGN.yaml** — 49 active instances + 3 `excluded_because` stubs across all nine guide sections (RBAC denials, OCC 412s, segregation-of-duties, deadline boundaries, overlap rules, pagination envelope, ledger immutability, immediate consistency).

## Key findings / notes
- Lint verdict (verbatim): `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (484 calls scanned, exit 0)
- Two self-consistency bugs were caught and fixed during the audit: `ERR_CLAIM_NOT_AGED_ENOUGH` was referenced in four transitions but missing from the §1.6 catalog (now declared and wired into validation priority 8), and `DUPLICATE_REVERSAL_CREDIT` was declared in the ledger enum but never produced (the duplicate-reject branch now posts it).
- Rule-8 interval semantics are genuinely differentiated: account freezes use closed-interval overlap (touching rejected), item hold windows use half-open (touching allowed), plus clearing-bank daily claim capacity as a third aggregate-capacity check covered in corner design.
- No forbidden concurrency vocabulary anywhere; zero unbound `${var}` placeholders across all 70 instances; every FK has a reverse-reachability GET.

## Step 3: Copy Shared Files — 2026-08-12T16:02:30.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1275_check_adjustment_return_item_processing/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-12T16:15:00.000Z

PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_1275_check_adjustment_return_item_processing/workspace/PRD.md`.

**Document structure** (domain-derived, not template-copied):
- §1 Introduction — 2 paragraphs from business context and lifecycle scope
- §2 Global Specifications — 11 subsections: RBAC (2.1), verbatim response envelope (2.2), pagination (2.3), logical clock & day reckoning (2.4), common resource properties incl. the `updated_at`/`version` absence for `CustomerNotification` and `LedgerEntry` (2.5), append-only ledger (2.6), balance derivation & auto freeze/thaw (2.7), integer-cents precision with pinned round-half-up steps (2.8), OCC (2.9), nested retrieval with all 11 not-found errors (2.10), explicit 11-step validation evaluation order (2.11)
- §3 Business Logic — 9 subsections by business process (master data/freezes → deposit & large-item review → presentment/duplicates/defects → payment/return/coding/fee → case work → claims & warranties → notifications & fee waiver → Reg CC recredit → daily sweep)
- §4 Endpoint table — 4 columns, 54 rows, verified against scaffold (methods, paths, and per-endpoint roles all match; six-role GETs rendered as "All roles")
- §5 Error catalogue — 2 columns, 40 rows, exact id/status match with scaffold

**Hard Contract Reports:**

```
Field coverage check:
- entities[].fields + common fields + endpoint inputs/query/path params: 101 required, 101 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] priority ordering: 11 checked, 11 expressed as an explicit ordered chain in §2.11, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write endpoint + expected_depositor_account_version/expected_adjustment_case_version + ERR_STALE_VERSION/412, no race framing), 0 missing
- state_machines[].transitions: all transitions across 10 machines checked and fully expressed (from/to states, per-transition preconditions paired with error ids, all cascades incl. bubble-up auto-close, breach-escalation, freeze/thaw), 0 missing
- calculations[]: 9 checked, 9 fully expressed in precise prose (incl. pinned per-component/per-day rounding with the 133333-cent→135-not-133 example, the Friday 2026-05-01→Monday 2026-05-11 aging example, half-open vs closed overlap semantics), 0 missing
- validations[] conditions: 11 checked, all matchable to their error ids in §2/§3 prose, 0 missing
- endpoints[].side_effects / applies_to: 54 checked, all expressed, 0 missing
- entities[].fields[] structured content: defaults, nullability, computed-field definitions all reconstructible from prose, 0 missing
- sibling-branch symmetry: settle SETTLED/DENIED, warranty HONORED/REJECTED, write-off from both from-states, assign from four from-states — all rendered with equal density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 524
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional verifications: §2.2 block is byte-identical to `section-2.2-response-structure.md` (fences stripped for comparison); all 40 error IDs mentioned in §1–§3; all 70+ state/enum values present verbatim; fuzzy-word and pseudocode-operator scans clean. The withheld difficulty/corner design files were not opened.

## Step 5: Generate Unit Tests — 2026-08-12T16:45:00.000Z

All verification gates pass. Task complete.

## Summary

Generated complete test infrastructure for task_1275 (Check Adjustment & Return Item Processing), driven strictly by the two design indices against PRD-verbatim citations.

**Stage 1 — `test_helpers/`** (9 modules):
- `types.py` — 13 entity TypedDicts + status/role enums; `CustomerNotification` and `LedgerEntry` correctly omit `updated_at`/`version` (PRD §2.5 light-resources rule)
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint (46 methods, incl. `/_clock/set_current_utc` and `/bank/ops/run-daily`)
- `api_errors.py` — all 40 error IDs with HTTP statuses, registered via `set_error_http_status_map`
- `assertions.py`, `factories.py` (unique-suffix counters for account_number/routing_number/item_reference), `constants.py` (fee tables, thresholds, default clock 2026-05-01T00:00:00Z)
- `test_users.py` — shared opaque-role headers + `make_*_headers` builders; `make_customer_headers(account_id)` for the entity-backed Customer role
- `fixtures.py` — composite chains: presented/paid/returned/coded items, encoding-error claims walked to SUBMITTED/ACKNOWLEDGED/DENIED/RESOLVED, large-item-under-review, image-warranty cases, recredit submitted/provisioned, ledger summation helpers

**Stage 2 — `test_suite/`**: conftest.py + 9 test files, **85 tests total**: all 18 difficulty instances covered by exactly 2 tests each, all 49 non-stub corner instances by 1 each. The 3 `excluded_because:` stubs were not translated (pointers verified to resolve).

**Audits run (all green):** py_compile; pytest collection (85 collected); tag-coverage audit (no shortfalls, no unknown tags, no stub translations); verbatim-citation audit (every docstring has a ≥8-word span surviving literal grep of PRD.md, `Design:` line last); structure audit (no skip/xfail, no scaffold references, one tag per test).

**PRD-first adjudication notes:**
- No instances were skipped — every non-stub instance has verbatim PRD coverage with uniquely-derivable outcomes (the PRD pins the validation order in §2.11 and §3.6 explicitly, the fee/interest rounding order in §2.8/§3.4/§3.8, and even the exact aging example "calendar 10 but business 6").
- Two translation corrections versus the raw recipes, both mandated by the two-reader rule: (a) timestamp assertions on `due_at`/`hold_until`/`deadline_at` use prefix matching since PRD pins fractional-second rendering only for `created_at`/`updated_at`/`api_request_timestamp`; (b) `hold_return_item_decision_cascades`' recipe indexed `notifications[0]`, which would capture the earlier LARGE_ITEM_HOLD_NOTICE — the test instead asserts existence of a PENDING DEPOSIT_REJECTED_NOTICE, the PRD-stated rule.
- `present_requires_clearing_bank_active`'s second test asserts the rejected present leaves the item RECEIVED with `presentment_count == 0` and that retry fails identically — claim-submit against a SUSPENDED bank is unreachable via the API (claims only exist after a successful present, which requires ACTIVE, and no endpoint suspends a bank afterwards).

## Step 6: Generate Implementation — 2026-08-12T16:45:30.000Z

Implementation complete. All 54 endpoints are implemented and smoke-tested.

## What was built

Python + Flask implementation in `/home/ubuntu/github/CodingPRD/tasks/task_1275_check_adjustment_return_item_processing/workspace/implementation/`:

- **`start.sh`** — foreground launcher with the guarded dependency install (`if ! python3 -c "import flask"`), `exec python3 app.py`, binds `0.0.0.0:$PORT` (default 10000). Verified booting over real HTTP.
- **`app.py`** — Flask app, blueprint registration, envelope-shaped error handlers (ApiError, HTTP 404/405, 500).
- **`db.py`** — empty in-memory store (no seeding), logical clock booting at exactly `2026-05-01T00:00:00Z` (never wall clock), UUID ids, 3-fractional-digit ISO timestamps, `version` starting at 1 with `touch()` bumps on every mutation.
- **`envelope.py`** — exact envelope (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`; pagination fields `limit`/`offset`/`total_count`/`has_more` in meta, limit default 10 clamped [1,100]).
- **`security.py`** — `X-User-ID`/`X-User-Role` auth (401), per-endpoint role lists (403), entity-backed Customer ownership (403).
- **`timeutil.py`** — business-day math matching the PRD example (Fri 2026-05-01 → Mon 2026-05-11 = 10 calendar / 6 business days, verified).
- **`domain.py`** — ledger posting, derived balances, cyclic auto freeze/thaw (with version bumps), fee computation (round-half-up of base×multiplier before surcharge, verified: HIGH_RISK NSF=3750, second NSF=4250), recredit per-day-rounded interest (verified: principal 133333 × 5 days → 135), case bubble-up auto-close, notification creation.
- **12 route modules** covering the full endpoint table.

## Key fidelity decisions

- **Claim submit order** follows PRD §3.6's explicit sequence (DRAFT → case ASSIGNED → window → capacity → suspended → amount), where it deliberately puts the capacity check before the bank-suspension check, overriding the generic priority ladder.
- **Freeze windows** are closed intervals (touching overlaps → 409); **hold windows** are half-open (touching allowed). Both verified.
- **Validation priority** per §2.11: auth → role → ownership → existence (left-to-right) → OCC (412) → state → segregation-of-duties → temporal → structural → cross-reference → amount/shape.
- Duplicate presentment selects the earliest-created PRESENTED/PAID same-reference item, posts `DUPLICATE_REVERSAL_CREDIT`, and does not increment `presentment_count` (per scaffold side effects).
- Customer notifications and ledger entries carry only `id`/`created_at` (no `updated_at`/`version`) per §2.5.

All smoke suites passed: basic deposit/present/pay ledger math, return coding + tiered fees + `returned_item_count_30d`, re-presentment gates (uncoded → `ERR_INVALID_STATE`, ineligible reason → `ERR_RE_PRESENTMENT_NOT_ELIGIBLE`, third presentment → `ERR_MAX_PRESENTMENTS_EXCEEDED`), large-item cascade (auto hold window `[created_at, +2 business days)`, decide RETURN_ITEM auto-resolving the case, run-daily expiry releasing the item), claim/warranty lifecycles with SoD and bubble-up close, aging/escalation/write-off thresholds (10/30 business days), Reg CC windows (40-day create, 45-day revoke), freeze windows blocking deposits, OCC 412s, Customer ownership scoping, and pagination meta. Fresh boots are state-empty.

## Step 7: Run Tests and Iterate — 2026-08-12T17:05:00.000Z

Pre-sweep route-parity check (orchestrator): implementation registers exactly the same 54 (method, path) pairs that SCAFFOLD.yaml declares — 0 missing, 0 extra.

Baseline sweep: 8 rounds × 85 tests → every round 77 passed / 8 failed, same 8 failures deterministically (no flakiness). Post-fix sweep verified by orchestrator on disk: all 8 rounds 85/85.

All 8 rounds pass 85/85. Sweep complete.

## Summary

- **Iterations run:** 2 (one prior sweep at 77/85 with 8 deterministic failures; one post-fix sweep at 85/85 × 8 rounds).

- **Tests deleted:** None. Every failing test traced to verbatim PRD prose; no PRD-silence or unique-derivability collapses found.

- **Fixes applied to `test_suite/`** (all were plain Python `NameError` / setup-data bugs — the assertions themselves were PRD-faithful):
  - `/home/ubuntu/github/CodingPRD/tasks/task_1275_check_adjustment_return_item_processing/test_suite/test_04_returns_fees_balances.py` — `_two_nsf_returns_high_risk(self)` and `_setup_deposit_then_pay(self)` referenced the `api` pytest fixture without receiving it; added `api` parameter and passed it from the 4 calling tests (fixes `test_first_nsf_return_fee_uses_base_times_risk_multiplier`, `test_second_nsf_return_fee_adds_first_surcharge_tier`, `test_available_includes_provisional_but_settled_excludes_it`, `test_balances_converge_after_payment`).
  - `/home/ubuntu/github/CodingPRD/tasks/task_1275_check_adjustment_return_item_processing/test_suite/test_06_adjustment_cases.py` — module-level `_resolved_return_case()` called `api.resolve_adjustment_case` with no `api` in scope; added `api` parameter, passed from both reopen-cycle tests.
  - `/home/ubuntu/github/CodingPRD/tasks/task_1275_check_adjustment_return_item_processing/test_suite/test_07_claims_and_warranties.py` — `_warranty_case_with_two_drafts(self)` same `api` scoping bug; fixed (fixes `test_warranty_submit_deadline_boundary`).
  - `/home/ubuntu/github/CodingPRD/tasks/task_1275_check_adjustment_return_item_processing/test_suite/test_03_presentment.py` — `test_image_quality_case_created_at_present` created items with `amount_cents=5000` but left `encoded_amount_cents` at the factory default 100000, so the presentment fired the PRD §3.3 ENCODING_ERROR detector alongside the IMAGE_WARRANTY detector (2 cases where the test expected 1). Added `encoded_amount_cents=5000` to both items so only the image-quality defect fires — making the setup faithful to the test's stated PRD §3.3 intent.

- **Fixes applied to `implementation/`:** None — the implementation was already PRD-correct; all 8 failures were test-side scoping/setup bugs.

## Step 8: Finalize PRD — 2026-08-12T17:02:00.000Z

`PRD_FINALIZED.md` is in place as a byte-copy of `PRD.md`. After auditing every Step 7 item against the implementation, I made **zero edits** — every Step 7 fix was a pure test-side bug (Python `NameError` scoping or setup data), and the PRD already uniquely determines each behavior involved.

**Line counts / delta**
- `PRD.md`: 328 lines; `PRD_FINALIZED.md`: 328 lines; 0% delta (verified identical via `diff`).

**Per-item verification (why no edit was warranted)**

1. **test_04_returns_fees_balances.py scoping fixes** (4 tests) — Subject: return-item fee math and balance derivation. PRD §3.4 already pins the formula verbatim (base 2500/3000/1500/0 × risk multiplier 1.0/1.5 rounded half-up first, then surcharge 0/500/1500 by prior-return count computed as `returned_item_count_30d` − 1); PRD §2.7 pins available = sum over all entries, settled = non-provisional only; §3.4 pins payment posting `PROVISIONAL_REVERSAL` + `SETTLEMENT_CREDIT` so balances converge. Impl matches at `workspace/implementation/domain.py:41-49` (balance derivation) and `domain.py:230-243` (fee computation). Failures were missing `api` fixture parameters — no PRD silence.

2. **test_06_adjustment_cases.py scoping fix** (reopen-cycle tests) — Subject: case reopen. PRD §3.5 already pins `RESOLVED → REOPENED` with `reopen_count` incrementing and prior `disposition`/`resolution_amount_cents`/`resolved_at` cleared, plus assignment permitted from `REOPENED`. Impl matches at `routes_cases.py:140-152` and `ASSIGNABLE_STATES` at `routes_cases.py:17`. Pure fixture scoping bug.

3. **test_07_claims_and_warranties.py scoping fix** (`test_warranty_submit_deadline_boundary`) — Subject: warranty submit deadline. PRD §3.6 already pins "submission is allowed only while the current logical time is on or before `deadline_at`". Impl matches at `routes_warranties.py:23` (rejects only when `now > deadline_at`). Pure fixture scoping bug.

4. **test_03_presentment.py setup fix** (`test_image_quality_case_created_at_present`) — Subject: presentment defect detectors. PRD §3.3 already pins both detectors running **independently** at presentment: `ENCODING_ERROR` case iff `encoded_amount_cents` differs from `amount_cents`; `IMAGE_WARRANTY` case iff `image_quality_score < 60`. Impl matches at `routes_items.py:188` and `routes_items.py:206`. The test's factory default left `encoded_amount_cents` mismatched, so the implementation *correctly* fired both detectors per PRD — the fix aligned the test setup with the test's stated single-detector intent, not with any PRD gap.

**Changes to PRD_FINALIZED.md:** none. Per-edit search log is empty because no edit was committed; the pre-edit enumeration above (fee math, balances, reopen cycle, warranty deadline, presentment detectors — each checked against all impl callsites in `domain.py`, `routes_cases.py`, `routes_warranties.py`, `routes_items.py`) confirmed the PRD prose is already uniquely determining and impl-consistent everywhere, so any wording change would have risked creating a new mismatch rather than fixing one.

## Step 9: Complete PRD — 2026-08-12T17:09:00.000Z

**File produced:** `/home/ubuntu/github/CodingPRD/tasks/task_1275_check_adjustment_return_item_processing/workspace/PRD_COMPLETED.md`

**Size delta:** PRD_FINALIZED.md 328 lines / 53,178 chars → PRD_COMPLETED.md 333 lines / 56,125 chars (+5 lines, +2,947 chars).

**Counts:** 8 ambiguity-pins, 3 mismatch-revisions (11 changes total).

### Changes

- **§2.1 (User and RBAC)** — insert — ambiguity — pinned Customer list scoping: mismatched `depositor_account_id` filter → `ERR_FORBIDDEN_OWNERSHIP`; otherwise filter forced to the caller's own id — `implementation/security.py:49-59`
- **§2.2 (Error Response Format)** — insert — ambiguity — pinned framework fallbacks: unrouted/HTTP-layer failures answered in the error envelope with `ERR_NOT_FOUND`; unexpected failures with `ERR_INTERNAL` (500) — `implementation/app.py:42-50`
- **§2.3 (Pagination)** — revise — mismatch — PRD said "min 1 max 100" without semantics; pinned impl's clamping (`limit` clamped to [1,100], `offset` to ≥0, non-integer → `ERR_INVALID_REQUEST` 400) — `implementation/envelope.py:44-58`
- **§2.3 (Pagination)** — revise — ambiguity — sort pinned as creation order with insertion-sequence tie-break (impl sorts by `_seq`, since logical-clock timestamps can tie) — `implementation/envelope.py:61-66`, `implementation/db.py:55-57`
- **§2.10 (Nested Retrieval)** — revise — mismatch — added the twelfth not-found error `ERR_LEDGER_ENTRY_NOT_FOUND` (404), used by ledger reads but absent from PRD — `implementation/routes_ledger.py:17`
- **§2.11 (Validation Order)** — insert — mismatch — pinned impl's actual ownership-vs-existence ordering: ownership-before-existence only where the account id is known without a lookup (account read, freeze list, account-scoped list filters, recredit creation); on item/case/notification/fee/recredit/ledger reads and per-item lists, existence resolves first so unknown ids 404 even for an ownership-failing Customer — `implementation/routes_accounts.py:55-56` vs `implementation/routes_items.py:123-124`, `routes_cases.py:46-47`, `routes_notifications.py:18-19`, `routes_fees.py:20-21`, `routes_recredits.py:107-108`, `routes_ledger.py:17-18`
- **§3.1 (Freeze Windows)** — insert — ambiguity — pinned required fields and `end_at < start_at` → `ERR_INVALID_REQUEST` 400 — `implementation/routes_accounts.py:104-109`
- **§3.2 (Deposit)** — insert — ambiguity — pinned deposit shape validation: all seven fields required; non-positive `amount_cents`, negative `encoded_amount_cents`, out-of-range score, bad channel → `ERR_INVALID_REQUEST` 400, evaluated after existence and frozen-account checks — `implementation/routes_items.py:36-69`
- **§3.4 (Reason Coding)** — insert — ambiguity — pinned invalid `reason_code` → `ERR_INVALID_REQUEST` 400 — `implementation/routes_items.py:286-289`
- **§3.6 (Adjustment Claims)** — insert — ambiguity — pinned manual-creation amount validation: missing/non-integer `claimed_amount_cents` → `ERR_INVALID_REQUEST` 400; non-positive → `ERR_INVALID_AMOUNT` 422 — `implementation/routes_cases.py:187-193`
- **§3.6 (Warranty Claims)** — insert — ambiguity — same creation-time `claimed_amount_cents` validation for warranty claims — `implementation/routes_cases.py:239-245`

### Cross-checked, no change needed
Claim-submit six-precondition order (§3.6) matches `routes_claims.py:20-48` exactly; fee formula/rounding, recredit per-day interest and example, `provisioned_late` (>2 business days), 40/45-day windows, hold overlap semantics, sweep jobs and response fields, duplicate detection (earliest-created match), segregation-of-duties, and all endpoint/role rows in §4 all match the implementation as written.
