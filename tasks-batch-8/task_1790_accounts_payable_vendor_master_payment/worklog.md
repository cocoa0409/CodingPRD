# Worklog — task_1790_accounts_payable_vendor_master_payment

Scenario: Accounts Payable Vendor Master & Payment Fraud Controls (shared services AP department): vendor creation with segregation-of-duties & documentation, bank detail change verification via callback to known contact, duplicate/fuzzy vendor detection & merge, sanctions/watchlist screening at setup & payment, dormant vendor deactivation, invoice approval matrix & threshold routing, payment file controls & positive pay integration, audit of master data changes

Difficulty directive from user: harder than expert level.

## Step 1: Create Task Directory — 2026-08-14T16:23:00.000Z

Task directory `tasks/task_1790_accounts_payable_vendor_master_payment/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline launcher; Step 1 treated as DONE per instructions. No index scan performed; no other task_* directory touched.

## Step 2: Generate Scaffold — 2026-08-14T17:28:00.000Z

Done. All three scaffold artifacts are written and pass the full audit chain. Note: `worklog.md` and `workspace/` already existed in the task directory (timestamped before my run); I did not touch them.

### Files written
- `/home/ubuntu/github/CodingPRD/tasks/task_1790_accounts_payable_vendor_master_payment/SCAFFOLD.yaml` — §1.0–§1.7 only (no design keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_1790_accounts_payable_vendor_master_payment/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level `scaffold_difficulty_design:`
- `/home/ubuntu/github/CodingPRD/tasks/task_1790_accounts_payable_vendor_master_payment/SCAFFOLD_CORNER_DESIGN.yaml` — single top-level `scaffold_corner_design:`

### Counts
- Entities: **14** (Vendor, VendorBankAccount, CallbackVerification, VendorDocument, WatchlistEntry, ScreeningCheck, SanctionsReviewCase, Invoice, InvoiceApproval, ApprovalMatrixRule, PaymentRun, Payment, VendorMergeRecord, AuditEvent)
- State machines: **10** (Vendor cyclic incl. DORMANT loop and MERGED terminal fan-in; Invoice reject/resubmit cycle; PaymentRun branching reverts + auto-demote; Payment, plus 6 smaller machines)
- Endpoints: **59** (incl. `POST /_clock/set_current_utc` with the mandated `2026-08-01T00:00:00Z` default, and `POST /vendor-sweeps/run` ops checkpoint)
- Errors: **38** (all referenced by ≥1 validation row — verified programmatically)
- Roles: **12**, all `identity: opaque`, segregation-of-duties model (6 explicit SoD rules)
- §1.8 instances: **18** (2 per rule × all 9 rules; every `distinguishing_aspect` names the rule's required distinction)
- §1.9 instances: **66** (62 active + 4 `excluded_because:` stubs); 827 total recipe calls
- Lint: `VERDICT: clean lint` (827 calls conform to §1.5; all FKs reverse-reachable); grounds resolvability, role closure, name uniqueness (84/84 unique), and forbidden-vocabulary scans all pass clean.

### Difficulty features baked in (per the harder-than-expert directive)
- **Multi-step chains**: 20–35-call recipes (full vendor onboarding → invoice tier chain → run compile/approve/release → positive-pay acks).
- **Race conditions (OCC only)**: 3 concurrency rules on `Vendor.version` (PATCH, merge-supersede, bank-account create), each with stale-412 + fresh-retry recipes.
- **Boundary precision**: matrix `[min,max)` at 499999/500000; Dice exactly 0.9000 hard-block vs 0.8966 review band (names computed by code: "Red Barn Feeds"/"Red Barn Feeda"); cooling-off at exactly +72h; dormancy at exactly 180/90 days; daily limit at exact equality.
- **Cross-entity invariants**: run-total-cents conservation across add/void; vendor actionable-invoice multiset conservation across suspend/reinstate.
- **Precedence ordering**: 38-row priority table with tested conflicts (state>safety on approve; safety>fiscal on release; constraint sub-ordering at submit).
- **Fuzzy thresholds**: pinned normalization + set-trigram Dice (4dp half-up) driving both duplicate detection (0.90/0.75) and sanctions screening (0.80), with computed scores in asserts.
- **Compound state+role+threshold**: tier = bracket + new-vendor bump + recent-bank bump, capped at 3; per-round SoD-5 scoping across role hats.
- **Cascades**: depth-4 CONFIRMED_HIT chain (case→vendor→invoice→payment→run demote) and depth-3 positive-pay mismatch chain with a pinned ordering trap (the mismatched payment's own invoice reverts to APPROVED then is re-held ON_HOLD by the vendor-suspend link).

### Design decisions to flag for downstream steps
- **Failed-request side effects (deliberate)**: payment-time screening at run add *fails* the request (ERR_SANCTIONS_REVIEW_PENDING / ERR_VENDOR_BLOCKED) yet still suspends/blocks the vendor and opens a case. The PRD must state this explicitly or an implementer will make the checks side-effect-free.
- **Live vs cached document validity**: business gates use live evaluation (`valid_from <= today <= valid_until`); `VendorDocument.status == EXPIRED` is only a sweep-maintained cache. A §1.9 instance locks this (payment add fails while the row still reads VALID).
- **Vendor.version bump surface**: vendor row mutations, bank-account create, and primary-supersede all bump `Vendor.version`; document/invoice creates do not. Recipes capture fresh versions via GET before every OCC call.
- **SoD is armed by shared create rights**: VendorManager can create vendors, APSupervisor/APManager can submit invoices, TreasuryManager can create runs — so every SoD rule is actually triggerable.
- **Exact-name screening via suffix stripping**: "Vortex Trading, Inc." normalizes to an exact watchlist match (HIT), which the PRD must explain carefully.
- **PATCH-name re-screening** is the testable path to a REVIEW outcome on an established vendor (used by the depth-4 cascade setup).
- **Path placeholders are `{id}`** everywhere (lint check (f) convention).

## Step 3: Copy Shared Files — 2026-08-14T17:29:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1790_accounts_payable_vendor_master_payment/workspace/INSTRUCTION.md` (verified present, 1424 bytes).

## Step 4: Generate PRD — 2026-08-14T17:52:00.000Z

The PRD is complete and all audits pass. Final summary:

### Task Complete

**Output file:** `/home/ubuntu/github/CodingPRD/tasks/task_1790_accounts_payable_vendor_master_payment/workspace/PRD.md`
**Line count:** 338 lines (~63 KB)

**Sections written:**
- **§1 Introduction** — 2 paragraphs (business-context + control-objectives angle)
- **§2 Global Specifications** — 11 subsections: 2.1 Roles/RBAC (all 12 roles, opaque-identity prose per role), 2.2 Response Structure (byte-identical verbatim block, verified programmatically), 2.3 Pagination, 2.4 Logical Clock & Vendor Sweep, 2.5 Common Resource Properties (incl. explicit absence of `updated_at`/`version` on ScreeningCheck/VendorMergeRecord/AuditEvent), 2.6 Segregation of Duties (SoD-1/2/3/4a/4b/5), 2.7 Audit Trail, 2.8 OCC (3 rules), 2.9 Precision/Rounding (pinned round-then-sum), 2.10 Name Normalization & Dice Similarity, 2.11 Validation Order & Nested Path Existence
- **§3 Business Logic** — 7 subsections organized on the business timeline: vendor intake/duplicates/documents → approval/watchlists/sanctions cases → bank accounts/callback verification → master-data edits/suspension/merge/dormancy → invoice intake/tiered approval → run assembly/payment-time screening → release/positive-pay settlement
- **§4 Endpoint table** — 59 rows (matches scaffold exactly), 4 columns only
- **§5 Error catalogue** — 38 rows (matches scaffold exactly), 2 columns only

**Hard Contract reports:**

```
Field coverage check:
- entities[].fields: 90 required, 90 present, 0 missing
- endpoints[].request_body: 59 required, 59 present, 0 missing
- endpoints[].query_params: 22 required, 22 present, 0 missing
- (also present: output-only ids current_utc, sweep counters, ack_result; 38/38 error ids; 32/32 states; 12/12 roles)
Status: PASS

Rule coverage check: all validations' priority orderings expressed per multi-check endpoint (create, approve-vendor, confirm, approve-invoice, run-add, release, merge, acks); 3/3 OCC rules with endpoint+field+error+412; all transitions across 10 state machines with preconditions/side effects; 11/11 calculations in precise prose (boundary semantics preserved: strict < bump windows, >= dormancy/limit boundaries, strict > callback expiry, inclusive document bounds); all applies_to scopes enumerated; structured field content (defaults, enums, nullability) reconstructible; sibling branches (CLEAR/REVIEW/HIT, MATCH/MISMATCH, CLEARED/CONFIRMED_HIT, 5 merge sources) at equal density. Three audit-event side effects (suspend, reinstate, matrix-rule create) were caught missing during the walk and repaired.
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 653
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

**Self-audit notes:**
- **Fully rendered:** every scaffold table (entities, state machines, concurrency rules, calculations, validations, endpoints, errors, roles) was projected into prose; constants embedded in business context (2,500-cent wire fee, 10,000,000-cent daily ceiling, 72-hour cooling-off, 30-day new-vendor window, 180/90-day dormancy, 48-hour callback expiry, 0.9000/0.7500/0.8000 thresholds).
- **Intentional generalizations:** (1) §4 uses "All roles" for the 14 read endpoints whose scaffold role list is exactly the 12 declared roles (full enumeration in §2.1); (2) the deactivation gate "no payments in `PENDING`/`RELEASED`" is stated without an error id because the scaffold nominates none for it; (3) ack item shape described as "identifying one payment and carrying an `ack_result` of `MATCH`/`MISMATCH`" without inventing an unnamed key.
- **No leaks:** `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened, grepped, or referenced; no sibling task directories were read. All numbers in the PRD come solely from the scaffold's `calculations`/`validations` tables — no test-recipe or worked-example values exist in the document. A programmatic scan confirmed no pseudocode operators (`>=`, `==`, `+=`, …) and no fuzzy hedging words in the prose.

## Step 6: Generate Implementation — 2026-08-14T18:35:00.000Z

Implementation complete and verified. Summary:

### Files written
All under `/home/ubuntu/github/CodingPRD/tasks/task_1790_accounts_payable_vendor_master_payment/workspace/implementation/`:

- `start.sh` — executable launcher; guarded dependency install (`if ! python3 -c "import flask"`), `exec python3 app.py` in foreground
- `requirements.txt` — flask
- `app.py` — Flask entry point, ApiError/404/405/500 handlers, blueprint registration; binds `0.0.0.0:$PORT` (default 10000)
- `db.py` — in-memory stores (plain dicts keyed by id, zero persistence) + logical clock defaulting to exactly `2026-08-01T00:00:00Z`; all timestamps derive from the logical clock
- `errors.py` — full 38-entry error catalog with exact IDs and HTTP statuses
- `response.py` — envelope: `meta.api_request_id` (`req_…`) / `api_request_timestamp` (3-fractional-digit ISO UTC), `response_type` object/array/error, pagination fields (`limit`/`offset`/`total_count`/`has_more`) in `meta` for lists
- `middleware.py` — auth (`X-User-ID`/`X-User-Role`, 12 roles), role checks, `TIER_ROLE` map, body/field validators, left-to-right existence, pagination (default 10, min 1, max 100, clamped)
- `services.py` — all business logic
- `routes_ops.py`, `routes_vendors.py`, `routes_bank.py`, `routes_compliance.py`, `routes_matrix.py`, `routes_invoices.py`, `routes_payments.py`, `routes_audit.py`

### Coverage
- **Endpoints: 59/59** implemented per the endpoint table (clock set, sweep, vendors CRUD + 9 lifecycle actions, merge records, bank accounts + callback verifications, documents, watchlist, screening checks, sanctions cases, matrix rules, invoices + approvals, payment runs lifecycle + positive-pay acks, payments, audit events). Confirmed non-endpoints (e.g. `GET /payment-runs` list, `GET /watchlist-entries/{id}`, `POST /payments`) return 404.
- **State machines: 10/10** — Vendor (incl. DRAFT/PENDING/ACTIVE/SUSPENDED/DORMANT/BLOCKED/MERGED/DEACTIVATED cycles), VendorBankAccount, CallbackVerification, VendorDocument, WatchlistEntry, SanctionsReviewCase, Invoice (8 states + hold/resume), PaymentRun (6 states + auto-demote + bubble-up close), Payment, ApprovalMatrixRule.
- **Calculations: 9/9** — name normalization (suffix tokens, exact transform), Dice trigram score (4dp ROUND_HALF_UP via `Decimal`, exact-equality short path, created_at-ASC tie-break), duplicate detection (strict tax_id leg → hard block 0.9000 → review band 0.7500), sanctions screening (setup/payment variants, 0.8000 fuzzy, BLOCK-vs-REVIEW at 1.0000), invoice approval routing (GLOBAL fallback, [min,max) brackets, strict-< 30-day/72-hour bumps, cap 3), invoice pay amount (provisional vs final variants, inclusive window end, per-invoice ROUND_HALF_UP), payment run totals (pinned round-then-sum order, 2500-cent wire fee), dormancy evaluation (>= 180d / >= 90d), callback attempt policy (3-strike lock, strict-> 48h expiry), daily release limit (<= 10,000,000 cents per logical UTC date).
- **Validation pipeline**: fixed order auth(1-2) → request shape(3) → path existence left-to-right(4) → OCC `expected_vendor_version`(5) → state incl. LOCKED/EXPIRED/already-terminal guards(6-9) → business-safety incl. all six SoD rules(10-20) → business constraints(21-34) → temporal(35-37) → fiscal(38), with endpoint-specific sub-orderings from PRD §3 (e.g. payment-run add: state → screening-with-persistent-side-effects → BLOCKED → REVIEW-pending → not-ACTIVE → bank verified → cooling-off → W9 live validity).

### Verified by smoke tests
120+ end-to-end assertions passed across 8 suites: envelope shape, auth/RBAC, duplicate bands, W9 closed-interval overlap and inclusive `valid_until == today`, SoD-1/2/3/4a/4b/5, tier ordering rules, provisional-vs-final discount divergence, cooling-off exactly-72h boundary, callback lock/expiry boundaries (confirmable at exactly `expires_at`), dormancy exactly-180d eligibility, merge with counts/match_score/audit, payment-time HIT block cascade (hold + VENDOR_BLOCKED voids + run demote), disposition CONFIRMED_HIT cascade, MISMATCH fraud chain (invoice ON_HOLD pre_hold=APPROVED, `fraud_hold_reason`), snapshot staleness, daily-limit exact-boundary, audit trail shape/role gating, pagination meta.

### Contract confirmation
`start.sh` reads `$PORT` (default 10000), binds `0.0.0.0`, runs in the foreground via `exec`, installs deps only when Flask is missing (per-test-reboot safe), and boots a completely fresh empty store on every invocation (verified: empty list responses, clock at default, zero sweep counters). No seeding, no disk persistence, no extra endpoints/fields beyond the PRD.

## Step 5: Generate Unit Tests — 2026-08-14T18:40:00.000Z

Generation complete. Summary below.

### Files written

**`test_helpers/` (Stage 1, 9 files)** — `/home/ubuntu/github/CodingPRD/tasks/task_1790_accounts_payable_vendor_master_payment/test_helpers/`
- `types.py` — 16 status/role enums + 14 entity TypedDicts; `ScreeningCheck`/`VendorMergeRecord`/`AuditEvent` correctly modeled as append-only (id + created_at only, no `updated_at`/`version`).
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint (58 methods).
- `api_errors.py` — all 38 `ApiErrorId`s + HTTP status map, registered via `set_error_http_status_map` at import.
- `assertions.py` — per-entity `assert_*` (append-only entities assert `version`/`updated_at` **absent** per PRD §2.5), `parse_timestamp`/`assert_timestamp_equals` for logical-clock comparisons, `assert_payment_invariants`, `assert_run_totals_consistent`.
- `factories.py`, `constants.py` (all PRD thresholds incl. `WIRE_FEE_CENTS=2500`, `TREASURY_DAILY_LIMIT_CENTS=10_000_000`, `TIER_ROLE` map), `test_users.py` (16 pre-built operator headers + per-tier approver map; all 12 roles are `identity: opaque` so shared constants are canonical), `fixtures.py` (composite chains: `onboard_vendor_to_active`, `add_verified_primary_bank_account` with OCC re-read, `approve_invoice_fully`, `build_released_run`, sweep/clock helpers, `wrong_verification_codes`), `__init__.py` barrel.

**`test_suite/` (Stage 2, 8 files, 97 tests)** — `conftest.py` (session `api` + 16 header fixtures) and `test_01`…`test_07` grouped by concern (registration/duplicates, vendor lifecycle/documents, merge/OCC/audit, bank/callbacks, invoice routing/approval, payment runs/release, settlement/fraud cascades).

### Coverage
- **Queue A: 18/18 instances, 36 tests** (exactly 2 per instance, both tagged `Design: Difficulty/<rule_id>/<name>`).
- **Queue B: 61/62 active instances, 61 tests** (1 per instance, tagged `Design: Corner/<section>/<name>`). All 4 `excluded_because:` stubs left untranslated; cross-references verified to resolve.

### Skipped instance (PRD-first filter)
- **Corner/endpoints/`pagination_limit_bounds_rejected`** — the test asserts `ERR_INVALID_REQUEST` for `limit=0`/`limit=101`, but PRD §2.3 only states the bounds ("a minimum of 1 and a maximum of 100") and §2.11's shape-violation enumeration never names an error for out-of-range pagination; two faithful readers could reject vs. clamp. No verbatim rule-bearing citation possible (fails C1/C2) → gap left as gap.

### Judgment calls made under the PRD-first rule
- **Version literals**: PRD §2.5 pins "increments by one on every mutation" but no initial value, so all version assertions are relational (`captured + 1`) instead of the recipes' absolute `== 2`/`== 3`.
- **Corner `double_ack_terminal_rejected`**: recipe's single-payment run closes after the first ack, making run-state and payment-terminal guards co-fire (PRD names no error for a non-RELEASED run). Translated with a two-payment run so the run stays RELEASED and `ERR_PAYMENT_ALREADY_TERMINAL` is the only derivable outcome.
- **Corner `payment_screening_uses_current_watchlist`**: recipe asserted "invoice stays APPROVED", which contradicts PRD §3.4's suspend hold-cascade (the APPROVED invoice is held on the payment-time REVIEW suspend). Asserted the PRD-derived outcome: `ON_HOLD` with `pre_hold_status == APPROVED`.
- **Difficulty `tier_routing_compound_bumps_capped`**: recipe confirmed the callback at clock 2026-08-10 for an account created 2026-08-01 (past the pinned 48h expiry). Setup re-ordered to create+confirm the account at 2026-08-10, preserving the intended `verified_at` semantics.
- **Dice scores** asserted (0.9630, 0.9000, 0.8966, 0.9565, 0.7097) were independently recomputed against the §2.10 algorithm and match the design-index values.

### Self-check results
- **Stage 1**: all 9 modules compile; barrel import verified; every `api.*`/`api_client.*` method used in tests exists on `ApiClient`; every `from test_helpers import ...` name resolves.
- **Stage 2**: 97/97 tests collect under pytest; every docstring ends with exactly one `Design:` line resolving to a real instance (no untagged, dual-tagged, stub-pointing, or dangling tags); all **164 PRD citations** verified verbatim against `workspace/PRD.md` (whitespace-normalized substring match); no `skip`/`skipif`/`xfail` markers; no scaffold/table references in comments or docstrings.

## Step 7: Test-Fix Iteration Loop — 2026-08-14T19:05:00.000Z

### Iteration 1
- **8-round parallel sweep**: 96/97 passed in every round; one consistent (non-flaky) failure in all 8 rounds.
- **Failing test**: `test_05_invoice_routing_and_approval.py::TestRoutingTiers::test_cost_center_rule_beats_global_fallback` — `AssertionError: cost-center rule wins / assert 3 == 2`.
- **Diagnosis (STEP 1 + STEP 2)**: the asserted rule (cost-center scope beats GLOBAL fallback) is verbatim in PRD §3.5 and uniquely derivable, so the test stays. But the test's SETUP was unfaithful to PRD §3.5's bump rule: the clock stayed at 2026-06-01 (the vendor's activation instant) through invoice submission, so "the submit time falls strictly before the instant thirty days after [first_activated_at]" fired the new-vendor bump on both invoices — required_tier was base+1 (3 and 2), not the asserted base tiers (2 and 1). The implementation returned the PRD-correct 3; the test fixture omitted the vendor-aging step every neighboring test in the same class performs.
- **Fix (test_suite/)**: added `set_clock("2026-08-01T00:00:00Z")` after `onboard_vendor_to_active` in that one test so submission happens 61 days post-activation and no bump confounds the scope-precedence assertion. No implementation change; no assertion weakened.

### Iteration 2 (verification sweep)
- Re-ran the full 8-round parallel sweep after the Iteration-1 test fix: **97/97 passed in all 8 rounds** (0 failed, 0 errors in every `results.{1..8}.json`). Note: one sweep launch was killed mid-flight by the host (wrapper exit 144; its 8 orphaned pytest runs had each printed "97 passed" but the runner wrappers died before writing results files), so the sweep was relaunched detached via `setsid nohup` and ran to completion with all 8 results files written.
- **Exit**: clean 8-round sweep achieved; no tests deleted, no implementation changes required.

## Final Status: PASS (97/97 x 8 rounds)

## Step 7: Run Tests and Iterate — 2026-08-14T18:58:00.000Z

### Summary

**Result: PASS — 97/97 tests in all 8 parallel rounds (0 failed, 0 errors per round).**

**Iterations run:** 2 (one diagnostic sweep identifying the failure, one clean verification sweep after the fix).

**Tests deleted:** none.

**Fixes applied to `test_suite/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1790_accounts_payable_vendor_master_payment/test_suite/test_05_invoice_routing_and_approval.py` — `TestRoutingTiers::test_cost_center_rule_beats_global_fallback`: added `set_clock("2026-08-01T00:00:00Z")` after `onboard_vendor_to_active` so invoice submission happens 61 days post-activation. The original setup left the clock at the activation instant (2026-06-01), so PRD §3.5's new-vendor tier bump ("submit time falls strictly before the instant thirty days after `first_activated_at`") fired on both submits, making required_tier 3 and 2 instead of the asserted 2 and 1. The implementation was PRD-correct; the test setup had omitted the vendor-aging step every neighboring test performs. The rule under test (cost-center scope beats GLOBAL fallback) is verbatim in PRD §3.5 and uniquely derivable, so the test was kept and its setup fixed — no assertion weakened.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `implementation/`:** none — the implementation was PRD-faithful throughout.

**Operational note:** one sweep's wrapper shell was killed mid-flight on the shared host (exit 144; its orphaned pytest runs had each printed "97 passed" but no results files were written). The sweep was relaunched with `setsid nohup` detachment and completed cleanly, with all 8 `results.{1..8}.json` files confirming 97/97.

## Step 8: Finalize PRD — 2026-08-14T19:05:00.000Z

PRD_FINALIZED.md is complete — a byte-identical copy of PRD.md with zero edits. The analysis below documents why.

### Summary

**PRD.md vs PRD_FINALIZED.md line counts and %-delta:** both files are 338 lines; 0% delta; `diff` confirms byte-identical.

**Changes:** none. Zero edits were made.

**Why zero edits — enumeration confirming the Step 7 item was a pure fixture bug:**

The single Step 7 item was a test-suite fix to `TestRoutingTiers::test_cost_center_rule_beats_global_fallback` (test_suite/test_05_invoice_routing_and_approval.py:161-189): a `set_clock("2026-08-01T00:00:00Z")` was added after `onboard_vendor_to_active` so the invoice submits happen 61 days after activation rather than at the activation instant.

(a) **Subject identified:** the §3.5 tier-routing rule — scope precedence (cost-center scope beats GLOBAL fallback) and the new-vendor tier bump (strict 30-day window from `first_activated_at`).

(b) **Impl paths enumerated and read:**
- `workspace/implementation/services.py:335-365` — `route_invoice_tier()`: scope filter `cost_center == invoice["cost_center"]` falling back to `"GLOBAL"` (lines 338-340); half-open bracket covering `min <= amount < max` with unset max unbounded (lines 342-347); new-vendor bump `submit_time < first_activated_at + timedelta(days=30)` with `NEW_VENDOR_DAYS = 30` (lines 352-356); bank bump `submit_time < verified_at + timedelta(hours=72)` (lines 357-364); cap `min(base + bumps, MAX_TIER)` (line 365). Every clause is verbatim-pinned by PRD §3.5 (PRD.md line 203), including the boundary gloss "a vendor exactly thirty days active earns no bump" matching the strict `<`.
- `workspace/implementation/routes_invoices.py:165-198` — the sole consumer `_submit_invoice`, shared by `/submit` (from `RECEIVED`) and `/resubmit` (from `REJECTED`); both re-snapshot `required_tier`, matching PRD §3.5's resubmit clause ("re-snapshotted against the current matrix and the current activation and bank-verification timestamps").
- `workspace/implementation/routes_vendors.py:114,245-246` — `first_activated_at` born `None`, stamped only when unset at first entry into `ACTIVE`; matches PRD §3.2 (line 163): "stamped with the logical time of this first entry into `ACTIVE` (later reactivations do not overwrite it)". The only other reader, `routes_ops.py:40` (dormancy sweep reference), matches PRD §3.4 (line 193) and is untouched by the Step 7 item.
- Test-helper evidence: `test_helpers/fixtures.py:107-123` — `onboard_vendor_to_active` approves the vendor at the current logical clock, so with the clock parked at 2026-06-01, `first_activated_at` = 2026-06-01T00:00:00Z and both submits in the original test fell strictly inside the 30-day window, adding +1 to each tier (3 and 2 instead of the asserted 2 and 1). Every neighboring test in `TestRoutingTiers` (e.g., `test_tier_routing_compound_bumps_capped_at_submit` at line 191) explicitly manages the clock around activation; this one test had omitted the aging step.

(c) **Wording adjustment:** none needed. The rule under test (cost-center scope beats GLOBAL fallback, and the strict 30-day new-vendor bump) is uniquely derivable from PRD §3.5 as written; the implementation is PRD-faithful; no assertion was weakened and no test was deleted. There is no PRD silence or PRD/impl mismatch to pin.

**Files:**
- `workspace/PRD_FINALIZED.md` (created, byte-identical to PRD.md)

## Step 9: Complete PRD — 2026-08-14T19:25:00.000Z

Done. PRD_COMPLETED.md is written at `workspace/PRD_COMPLETED.md` with 20 inline edits (19 diff hunks), no lines added or removed, no new sections.

### Summary

**Source vs output**: PRD_FINALIZED.md (source, byte-identical to PRD.md) — 338 lines / 63,580 bytes; PRD_COMPLETED.md — 338 lines / 65,828 bytes. Delta: +2,248 bytes (+2,226 chars). Line count unchanged; every change is an in-paragraph insert/revision.

**Counts**: 17 ambiguity-pins, 3 mismatch-revisions.

**Changes** (one bullet each; all paths under `workspace/implementation/`):

- §2.3 — insert — ambiguity — non-integer `limit`/`offset` rejected with `ERR_INVALID_REQUEST`; out-of-range integers clamped (limit to [1,100], offset to 0); equal creation timestamps keep relative creation order — middleware.py:195-223
- §2.4 — insert — ambiguity — the sweep's deactivation and document-expiry passes each append a `STATUS_CHANGE` audit event per record moved — routes_ops.py:69,77
- §2.5 — insert — ambiguity — `version` starts at 1 on creation — db.py:67
- §2.10 — revise — mismatch — normalization step 2 replaces every character outside `A`–`Z`/`0`–`9` (post-uppercase) with a space, not "not a letter or digit" (impl drops non-ASCII letters) — services.py:60
- §3.1 — insert — ambiguity — `name_contains` is a case-insensitive substring match against `legal_name` and, when present, `dba_name` — routes_vendors.py:134-139
- §3.1 — insert — ambiguity — document overlap gate consults every existing document of that `doc_type` regardless of status, including `SUPERSEDED`/`EXPIRED` — routes_bank.py:238-243
- §3.2 — insert — ambiguity — with no `ACTIVE` watchlist entries the result is `CLEAR` and the persisted row records `match_score` 0.0000 — services.py:132-135
- §3.2 — insert — ambiguity — disposition note is supplied as `note` or `disposition_note` (both accepted), stored as `disposition_note` — routes_compliance.py:121-123
- §3.3 — revise — mismatch — dropped the "nine-digit `routing_number`" implication; account/routing/holder fields are opaque strings with no format validation — routes_bank.py:55-57
- §3.3 — insert — ambiguity — a still-`PENDING` verification presented after `expires_at` is rejected with `ERR_CALLBACK_EXPIRED` (live expiry check) — routes_bank.py:136-137
- §3.3 — insert — ambiguity — on the third mismatch the parent account's move to `REJECTED` appends a `STATUS_CHANGE` audit event — routes_bank.py:154-155
- §3.4 — insert — ambiguity — vendor PATCH: payload fields outside the editable list (other than `tax_id`) are ignored; string fields may be set to null; the three numeric fields must be numeric when present — routes_vendors.py:161-178
- §3.4 — insert — ambiguity — name-edit re-screen `REVIEW` against an already-`SUSPENDED` vendor leaves it `SUSPENDED` and opens a case unless one is already `OPEN` — routes_vendors.py:199-208
- §3.4 — insert — ambiguity — once stamped, `fraud_hold_reason` persists; no transition (incl. reinstatement) clears it — services.py:259-271
- §3.4 — insert — ambiguity — deactivation's in-flight-payments gate violation is also rejected with `ERR_VENDOR_HAS_OPEN_INVOICES` — routes_vendors.py:344-346
- §3.4 — insert — ambiguity — merge collision is checked against the survivor's own non-`CANCELLED` invoices — routes_vendors.py:379-391
- §3.5 — insert — ambiguity — invoice edit ignores other supplied fields; a colliding corrected `invoice_number` is rejected with `ERR_DUPLICATE_INVOICE_NUMBER` — routes_invoices.py:139-158
- §3.5 — revise — mismatch — invoice rejection appends a `STATUS_CHANGE` audit event but the supplied reason is not recorded on it (was "recorded with the supplied reason") — routes_invoices.py:264-269
- §3.7 — insert — ambiguity — demotion of an `APPROVED` run to `COMPILED` (manual void or block cascade) clears `approved_by_user_id` to null — services.py:322-324, routes_payments.py:165-167
- §3.7 — insert — ambiguity — positive-pay acks: run-`RELEASED` check fires before items are examined; the batch is pre-validated atomically (no partial application); unknown/foreign payment → `ERR_NOT_FOUND`; a payment appearing twice in one batch → `ERR_PAYMENT_ALREADY_TERMINAL` — routes_payments.py:317-347

Everything else in the implementation — endpoint surface and roles, envelope shapes, state machines, guard orderings, thresholds and boundary semantics (180/90-day, 72-hour, 48-hour, 30-day, exactly-at-limit release), discount/fee/run-total math, duplicate and screening scoring, SoD rules, cascades, and the error catalogue — was already uniquely pinned by the PRD and left untouched.
