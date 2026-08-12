# Worklog — task_1262_property_restoration_estimating_insurance

## Step 1: Create Task Directory — 2026-08-12T11:29:00.000Z

Task directory pre-assigned as `tasks/task_1262_property_restoration_estimating_insurance` with `workspace/` subdirectory; verified both exist. Step 1 treated as done per orchestration instruction (no auto-index scan run).

## Step 2: Generate Scaffold — 2026-08-12T12:40:00.000Z

Scaffold generation complete. All three artifacts are written to `/home/ubuntu/github/CodingPRD/tasks/task_1262_property_restoration_estimating_insurance/` and the lint verdict is clean.

**Files**
- `SCAFFOLD.yaml` — §1.0–§1.7 (no difficulty/corner keys): 17 entities, 11 state machines, 3 OCC concurrency rules, 12 calculations, 33 prioritized validations, 73 endpoints, 31 error codes, 5 roles
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 19 instances, ≥2 per each of the 9 difficulty rules
- `SCAFFOLD_CORNER_DESIGN.yaml` — 59 instances (49 active + 10 `excluded_because` stubs) across all 9 claim-extraction-guide sections

**Lint verdict (verbatim)**: `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (73 endpoints, 17 entities, 19 §1.8 + 49 §1.9 instances, 987 calls scanned.)

**Harder-than-expert design choices**
- Archetype: multi-party negotiation + ledger reconciliation; flat topology, cyclic machines, segregation-of-duties role model (invoice void barred to its creator).
- Dual-variant calcs in two domains: provisional-vs-final RCV/ACV money (approval 5,876,000¢ vs invoice 5,684,000¢; recovery capped 608,000¢ ≠ 800,000¢ projected) and mean-vs-worst drying-day classification on inspections (2 vs 3 days, same readings).
- Combinatorial formulas in all three modes: (a) O&P three-trade gate with sequential 10%-then-10% compounding (63¢ on 300¢ base at exactly 3 trades), (b) pinned per-line-then-sum rounding (201¢ vs 200¢), (c) deductible→advance→recovery evaluation-order pin (advance 110,000¢, recovery 40,000¢).
- Cyclic machines on Estimate (SUBMITTED→COUNTERED→REVISED→SUBMITTED) and Payment (…→RETURNED→REQUESTED); Claim carries IN_PROGRESS↔ON_HOLD drift hold plus auto transitions.
- Depth-3 cascade (supplement approval → claim aggregates → WA void for >10% scope drift → claim ON_HOLD) and depth-2 cascade (invoice issue → auto recovery payment → posture flip).
- Temporal rules with two interval semantics (half-open price windows vs 30-minute buffered inspection scheduling) on a logical clock defaulting to 2026-05-01T00:00:00Z, which also drives negotiation-round deemed-acceptance expiry.

**Fixes applied during self-review**: added the missing CodeUpgrade entity/machine; quoted YAML flow-sequence hazards (`field?`, `Entity[]`, bracketed `grounds`); added reverse-reachability GETs; removed an unreachable `ERR_ROUND_ALREADY_OPEN` (round creation moves the estimate out of SUBMITTED, so the guard could never fire — replaced with a reachable state-gate corner); removed a shadowed WA precondition on payment approval and instead added a start-work edge from APPROVED so `ERR_AUTHORIZATION_MISSING` is reachable; made one fixture's moisture reading dry so `complete-work` can legitimately pass the gate in the provisional/final instance; corrected two hand-computed literals (advance 110,000¢ / recovery 40,000¢) after executing the pinned formulas in Python.

## Step 3: Copy Shared Files — 2026-08-12T12:41:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1262_property_restoration_estimating_insurance/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-12T13:05:00.000Z

PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_1262_property_restoration_estimating_insurance/workspace/PRD.md` (344 lines). The withheld files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were not read or referenced.

**Structure:**
- §1 Introduction (2 paragraphs, business-context angle)
- §2 Global Specifications (9 subsections): RBAC with per-role `identity` translations (`Customer` entity-backed; four opaque staff roles), the fixed verbatim §2.2 response envelope, pagination (limit 10/1/100, offset 0, `created_at` ascending), the logical clock (startup 2026-05-01T00:00:00Z, expiry sweep), common resource properties, left-to-right reference resolution, the 10-tier validation priority chain, integer-cents/round-half-up discipline, and the three OCC rules with exact `expected_*_version` fields → `ERR_STALE_VERSION` (412)
- §3 Business Logic (9 lifecycle-ordered subsections): carrier/price-list config, policy & claim intake, loss assessment (evidence gates, both drying-day variants), estimate composition (per-line rounding with the pinned 201-vs-200 example, tax, O&P two-stage compounding with trade gate, depreciation split), submission/negotiation/deemed-acceptance, supplements & the scope-drift cascade (strictly >10% voids), ordinance waterfall, work authorization & execution gates, invoicing/payment ledger with posture and compensation paths
- §4 endpoint table (71 rows, 4 columns only); §5 error catalogue (31 errors, 2 columns only)

**Hard Contract Reports:**

```
Field coverage check:
- entities[].fields: 114 required, 114 present, 0 missing
- endpoints[].request_body/input (incl. query params): 74 required, 74 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority: 26 checked, 26 expressed (10-tier chain in §2.7 + per-endpoint evaluation orders in §3), 0 missing
- concurrency_rules[] OCC rejections: 3 checked, 3 expressed (write_endpoint + expected_<parent>_version + ERR_STALE_VERSION/412 all named), 0 missing
- state_machines[].transitions: 58 checked, 58 fully expressed, 0 missing
- calculations[]: 12 checked, 12 fully expressed in reconstructible prose (no pseudocode, no fuzzy words), 0 missing
- validations[] conditions: 26 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: all expressed (clock sweep, estimate locking, record-actuals no-recompute, supplement spawn, compensation cascades), 0 missing
- entities[].fields[] structured content (defaults, derived formulas, nullability): all reconstructible from prose, 0 missing
- sibling-branch symmetry: all sibling transition groups (claim manual edges, disposition ACCEPT/REJECT, invoice DRAFT/ISSUED void, payment RETURNED paths) rendered with equal density, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 641
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

All role names, 38 state enum values, and all field-level enum values (`MATERIAL`/`LABOR`/`EQUIPMENT`, `FLAT`/`PERCENT_OF_COVERAGE_A`, five `cause_of_loss` values, five photo tags, payment types/directions, postures) verified present verbatim in backticks.

## Step 5: Generate Unit Tests — 2026-08-12T13:55:00.000Z

Test generation complete for task_1262. Summary of what was produced and the key decisions:

**Generated** (under `/home/ubuntu/github/CodingPRD/tasks/task_1262_property_restoration_estimating_insurance/`):

- `test_helpers/` (9 files): `types.py` (17 TypedDicts + 17 enums), `api_client.py` (one method per PRD §4 endpoint, subclassing `GenericApiClient`), `api_errors.py` (all 31 error IDs + HTTP map registered with the framework), `assertions.py`, `factories.py`, `constants.py`, `test_users.py` (shared headers for opaque roles + `make_customer_headers`/`make_contractor_admin_headers` builders for the entity-backed Customer role and the invoice-void SoD rule), and `fixtures.py` (layered composites: claim bootstrap → state progression → completed inspection → estimate lifecycle → WA/advance → IN_PROGRESS/COMPLETE/INVOICED, plus supplement/negotiation helpers).
- `test_suite/`: `conftest.py` + 11 domain-named test files, **87 test functions**.

**Coverage audit (all green)**: all 19 difficulty instances have ≥2 tests tagged `Design: Difficulty/<rule_id>/<name>`; all 49 non-stub corner instances have ≥1 test tagged `Design: Corner/<section>/<name>`; all 10 `excluded_because:` stubs resolve to real difficulty instances and were not translated; zero orphan tags; every docstring ends with exactly one Design line; all 144 quoted PRD citations verified verbatim against `PRD.md`; no skip/xfail markers; no scaffold references in comments.

**Notable PRD-first adjudications** (design index vs PRD conflicts, resolved in PRD's favor):
1. `payment_return_requeue_cycle` asserted `payment_posture == UNPAID` after returning the advance while an invoice is ISSUED — PRD §3.9 uniquely derives `DEPRECIATION_PENDING` ("while an active invoice is `ISSUED` but unsettled"), so the test asserts the PRD value.
2. `payment_clear_and_return_preserve_invoice_balance` asserted `outstanding == 500,000` at issue — but the advance is CLEARED before invoice creation, and PRD §3.9's applied_cents definition (sum of CLEARED payments, capped at total) yields 50,000; the test asserts the PRD-consistent conserved quantity (500,000 = 50,000 + 450,000), which also matches the instance's own later assertions.
3. `complete_work_moisture_gate_blocks_then_passes` created a VERIFICATION inspection while the claim was IN_PROGRESS — illegal per PRD §3.3 (inspection creation only in INTAKE/ASSESSING). The test keeps the instance's assertions but reschedules legally: both inspections are created while ASSESSING; the verification inspection stays SCHEDULED (readings are allowed in that state) and is completed after the first gate failure.
4. `photo_requires_exactly_one_parent_rejected`'s both-parents sub-case used a non-resolving `supplement_id` (would yield 404 at priority 3, not the asserted 400). The test builds a real supplement so both parents resolve, making the 400 shape failure uniquely derivable; the SUPPLEMENT_EVIDENCE-under-inspection sub-case was dropped (PRD states only the converse direction).
5. `disposition_for_other_estimates_line_rejected` used the estimate's own id as a line id (ambiguous 404-vs-422); the test uses a second claim's real estimate line so the mismatch rule (422) is uniquely derived.
6. Exact-timestamp string assertions (`expires_at`, `due_at`) were relaxed to parsed-datetime equality, since the PRD pins "exactly 30 days later" / "creation time plus negotiation_response_days" but not the rendering format.

## Step 6: Generate Implementation — 2026-08-12T13:55:00.000Z

Implementation complete. Summary of what was built and verified:

## Deliverables (all under `/home/ubuntu/github/CodingPRD/tasks/task_1262_property_restoration_estimating_insurance/workspace/implementation/`)

- **`start.sh`** — executable launcher: guarded dependency install (`if ! python3 -c "import flask"` so per-test reboots skip pip), then `exec python3 app.py` in the foreground.
- **`app.py`** — Flask app factory, envelope-shaped error handlers (incl. 404/405 fallback), `0.0.0.0:$PORT` (default 10000), `static_folder=None` so exactly the 73 declared routes are registered.
- **`store.py`** — in-memory dicts keyed by id (17 tables, zero seeding), logical clock starting at exactly `2026-05-01T00:00:00Z`, Decimal-based `round_half_up`, UUID ids, version/timestamp stamping.
- **`errors.py`** — response envelope (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`), full 31-entry error catalog with exact HTTP statuses, auth middleware (`X-User-ID`/`X-User-Role`, 5 roles), payload validators, pagination (`limit` default 10/min 1/max 100, `offset`, `total_count`, `has_more`, `created_at` ASC).
- **`domain.py`** — all §1.3 calculations: per-line-then-sum extended pricing (verified the pinned 3×0.335@199 → 201 case), per-line sales tax, O&P trade-gate with sequential compounding, depreciation split, claim roll-ups over {APPROVED, LOCKED} (claim `rcv_total_cents` = sum of estimate **grand** totals), deductible snapshot, ACV advance netting, depreciation-recovery waterfall with the pinned evaluation order, ordinance bucket waterfall, drying-day dual variants, payment posture, scope-drift check (strictly-greater on the rounded 10% threshold), and the round-expiry deemed-acceptance sweep.
- **`routes_a.py` / `routes_b.py`** — all 73 endpoints with the PRD §2.7 priority order enforced (auth → role/ownership/SoD → existence → payload → OCC → state → safety → business → temporal → fiscal).

## Key fidelity decisions
- **Timestamps**: lifecycle stamps (`submitted_at`, `due_at`, `expires_at`, etc.) render the logical clock canonically (whole-second values as `...Z` without fractions, so they string-match clock input); `created_at`/`updated_at` use the logical clock with the mandated 3 fractional digits; `meta.api_request_timestamp` is wall clock. `due_at = created_at + negotiation_response_days` is instant-consistent because `created_at` is clock-derived.
- **PRD-over-scaffold**: estimate submit's empty-lines check is `ERR_INVALID_REQUEST` (PRD §3.5 explicit), not `ERR_INSPECTION_INCOMPLETE`; respond checks disposition status before round status; complete-work checks moisture gate before code-upgrade gate.
- **Second-invoice compensation**: final-variant totals computed over {APPROVED, LOCKED} so a corrected invoice after void reproduces totals (a VOIDED-then-recreated invoice would otherwise total 0).
- Customer-role ownership returns 404 on all claim-scoped resources; payment creation enforces Customer→DEDUCTIBLE / ContractorAdmin→CUSTOMER_BALANCE exclusivity (403) and rejects manual carrier-direction types (400).

## Verification
Three end-to-end suites (~120 assertions) run against fresh `start.sh` boots — all pass: full happy path (carrier→policy→claim→inspection→estimate→negotiation→concede→WA sign w/ auto ACV advance→work→supplement w/ scope-drift void→ON_HOLD→re-sign→complete→invoice→recovery payment→settle→CLOSED), expiry sweep (exact `due_at` does not expire; +1s does), moisture/containment/ordinance/SoD/fiscal-cap gates, OCC 412s on all three guarded endpoints, clawback/requeue, and pagination. Boot contract verified: `bash start.sh` → HTTP 200 on `0.0.0.0:10000` in ~0.66s; reboot wipes all state (created resource 404s after restart); no seeding anywhere.

## Route parity check (orchestrator-run, pre-Step-7) — 2026-08-12T13:58:00.000Z

Loaded the Flask app and enumerated `url_map`: 73 declared endpoints in SCAFFOLD.yaml vs 73 registered routes; MISSING/EXTRA sets are empty after normalizing path-parameter names (`{id}` in scaffold ↔ `<cid>`/`<eid>`/etc. in Flask). Route parity PASS.

## Step 7: Run Tests and Iterate — 2026-08-12T14:00:00.000Z

All 8 rounds pass 87/87. Clean exit.

**Summary**

- **Iterations run:** 2 (first sweep surfaced the failures; factory fix + re-sweep confirmed clean).
- **Tests deleted:** none.
- **Fixes applied to `test_helpers/`:**
  - `/home/ubuntu/github/CodingPRD/tasks/task_1262_property_restoration_estimating_insurance/test_helpers/factories.py` — `create_policy_payload()`: the `FLAT`-oriented default `flat_deductible_cents: 50000` leaked into merged payloads when callers overrode only `deductible_type`/`deductible_pct` to build a `PERCENT_OF_COVERAGE_A` policy. PRD §3.2 (line 146) states verbatim: "Supplying the wrong field for the declared type — or omitting the required one — is rejected with `ERR_INVALID_REQUEST`." The PRD-faithful implementation correctly rejected the malformed fixture payload (HTTP 400 in setup). Fix: after merging overrides, pop `flat_deductible_cents` when the resolved type is `PERCENT_OF_COVERAGE_A` (and symmetrically pop `deductible_pct` when `FLAT`), unless the caller explicitly passed that field to exercise the rejection path.
- **Fixes applied to `test_suite/`:** none — both failing tests (`test_deductible_recovery_evaluation_order`, `test_zero_gap_produces_no_recovery_payment` in `test_09_invoicing_and_recovery.py`) assert PRD §3.2/§3.9 rules verbatim; their assertions were faithful.
- **Fixes applied to `implementation/`:** none — the 400 rejection was exactly the PRD-required behavior; the fixture was the bug (STEP 2, not STEP 3).

Final state: 8/8 rounds × 87/87 tests passed, zero flakiness across the sweep.

**Orchestrator verification**: all 8 `results.{1..8}.json` files confirmed on disk, each reporting `passed: 87, total: 87, failed: 0`.

## Step 8: Finalize PRD — 2026-08-12T14:05:00.000Z

All verification is complete. PRD_FINALIZED.md is finalized at the target path as a byte-identical copy of PRD.md — no edits were warranted. Here is the full report.

## Analysis

**The single `<step_7_diff>` item is a pure fixture bug with zero PRD delta.** The only Step 7 fix was to `test_helpers/factories.py` (`create_policy_payload()`): its FLAT-oriented default `flat_deductible_cents: 50000` leaked into merged `PERCENT_OF_COVERAGE_A` payloads, and the implementation correctly rejected those malformed payloads with HTTP 400. No `implementation/` fix, no test deletions, no `test_suite/` fix.

**The PRD already pins this behavior verbatim.** PRD §3.2 (line 146) states: *"The deductible terms are governed by `deductible_type`: when it is `FLAT`, `flat_deductible_cents` is required; when it is `PERCENT_OF_COVERAGE_A`, `deductible_pct` is required instead. Supplying the wrong field for the declared type — or omitting the required one — is rejected with `ERR_INVALID_REQUEST`."* This is exactly what the implementation does at `routes_a.py:150-167` (wrong non-null field → `ERR_INVALID_REQUEST`; required field missing or null → `ERR_INVALID_REQUEST` via `req_field` at errors.py:116-119). The validation's priority tier is also already pinned by §2.7 item 4 ("the deductible field matching the policy's `deductible_type`", line 108). Per the method ("not every item is a PRD silence (some are pure fixture bugs)"), no patch applies.

## Summary on exit

**Line counts:** PRD.md = 344 lines; PRD_FINALIZED.md = 344 lines; **0% delta** (byte-identical, confirmed by `diff`).

**Changes:** none.
- (no bullets — zero inserts, zero revisions)

**Per-edit pre-edit search log:** no edits were committed. For the single candidate edit evaluated and rejected (pinning deductible-field validation in §3.2), the mandatory search was still performed:
- (a) **Subject identified:** policy-creation deductible-field validation — wrong-field rejection and required-field enforcement keyed off `deductible_type`.
- (b) **Impl paths enumerated and read/grepped:** an impl-wide grep for `flat_deductible_cents`, `deductible_pct`, `deductible_type` across all `*.py` confirmed `routes_a.py` is the **only** file touching the subject — creation-time validation (routes_a.py:150-167, including the enum check, the `is not None` wrong-field guards at lines 159/164, and `req_field` required-field enforcement at lines 161/166 backed by errors.py:116-119) and the claim-intake deductible snapshot reader (routes_a.py:217-220). Also read: `test_helpers/factories.py:39-62` (the Step 7 fix site), `errors.py` field-coercion helpers, and all `test_suite/` usages of the two fields (test_01, test_04, test_05, test_07, test_08, test_09, test_10, test_11) to confirm no test pins anything beyond the PRD sentence.
- (c) **Wording outcome:** no wording committed — the existing §3.2 sentence already describes every enumerated path exactly, so any insert would have added scope without Step 7 justification and risked violating the NO-NEW-MISMATCH rule (e.g., the impl's tolerance of an explicit `null` for the wrong field was never exercised by Step 7 and is correctly left undetermined per the HARD SCOPE "Nothing else" clause).

**Deliverable:** `/home/ubuntu/github/CodingPRD/tasks/task_1262_property_restoration_estimating_insurance/workspace/PRD_FINALIZED.md` — a fresh implementer reading it (identical to PRD.md) is already fully pinned on the only behavior Step 7 touched.

## Step 9: Complete PRD — 2026-08-12T14:15:00.000Z

PRD_COMPLETED.md produced at `/home/ubuntu/github/CodingPRD/tasks/task_1262_property_restoration_estimating_insurance/workspace/PRD_COMPLETED.md`.

## Summary

- **Source**: `PRD_FINALIZED.md` (344 lines, 59,824 chars) → `PRD_COMPLETED.md` (346 lines, 62,293 chars; **+2 lines, +2,469 chars**).
- **Counts**: 9 ambiguity-pins, 3 mismatch-revisions (12 edits total across 10 edit sites; the §3.5 site contained two parallel revisions).

### Changes

- **§2.2 Error format** — insert — ambiguity — pinned envelope behavior for routing-level failures: unknown path → `ERR_RESOURCE_NOT_FOUND` (404); wrong method on known path → `ERR_RESOURCE_NOT_FOUND` at HTTP 405; framework-unparseable request → `ERR_INVALID_REQUEST` (400); unexpected internal failure → `ERR_INVALID_REQUEST` at 500 — `implementation/app.py:20-39`.
- **§2.3 Pagination** — insert — ambiguity — non-integer `limit`/`offset`, `limit` outside 1–100, or negative `offset` → `ERR_INVALID_REQUEST`; `created_at` ties break by insertion order; `has_more` = `offset` + returned items < `total_count` — `implementation/errors.py:167-198, 64-71`.
- **§2.4 Logical clock** — insert — ambiguity — `expired_round_ids` listed in round-creation order; datetime inputs are ISO 8601 with offset-less inputs read as UTC; logical-clock stamps render with `Z` suffix and fractional seconds only at sub-second precision (unlike `created_at`/`updated_at`) — `implementation/domain.py:320-328`, `implementation/store.py:62-97`.
- **§2.5 Common properties** — insert — mismatch — pure recomputation of derived aggregates (estimate totals, claim money/ledger counters, `ordinance_consumed_cents`, round `disputed_amount_cents`) refreshes `updated_at` without incrementing `version`, qualifying the prior blanket "increments on every mutation" — `implementation/store.py:130-140`, `implementation/domain.py:123-232`.
- **§2.7 Validation priority 4** — insert — ambiguity — body must be a JSON object; absent body treated as empty; unrecognized fields ignored — `implementation/errors.py:103-109`.
- **§3.5 Negotiation (round creation + append)** — revise — mismatch — disposition creation flips only a targeted line still `PENDING` to `DISPUTED`; a targeted `REMOVED` line keeps its status (previously pinned flatly as "becomes DISPUTED") — `implementation/routes_b.py:413-416`.
- **§3.7 Code upgrades** — insert — ambiguity — supplied `approved_cost_cents` must be strictly positive; approval (not denial) on a terminal claim → `ERR_INVALID_STATE_TRANSITION` — `implementation/routes_b.py:684-695`.
- **§3.8 Record-actuals** — insert — ambiguity — `qty_actual` must be ≥ 0; unresolvable `estimate_line_id` → `ERR_RESOURCE_NOT_FOUND`; line of another estimate → `ERR_INVALID_REQUEST` — `implementation/routes_b.py:351-366`.
- **§3.9 Invoice creation** — insert — ambiguity — `applied_cents` initialized at creation to the claim's already-`CLEARED` payment total capped at `total_cents`, `outstanding_cents` the difference — `implementation/routes_b.py:831-840`.
- **§3.9 Payments** — insert/revise — ambiguity ×2 — manual recording of carrier-direction types → `ERR_INVALID_REQUEST`; `CUSTOMER_BALANCE` outstanding-cap applies only once the active invoice is `ISSUED`/`SETTLED`, not while `DRAFT` — `implementation/routes_b.py:949-966`.

All other implementation behavior (endpoint set, role lists, state machines, money formulas, gates, cascade effects, response shapes) was already uniquely pinned by the PRD and verified against the code with no change needed.
