## Step 2: Generate Scaffold — 2026-08-14T00:28:00.000Z

Step 2 complete. All three scaffold artifacts are generated and lint-clean.

## Deliverables

All under `/home/ubuntu/github/CodingPRD/tasks/task_1586_naming_rights_sponsorship_fulfillment/`:

- **SCAFFOLD.yaml** — §1.0–§1.7 (no design keys): 12 entities, 11 state machines, 9 calculations, 29 ordered validation rows (10 priority tiers), 50 endpoints, 31 error codes, 5 roles.
- **SCAFFOLD_DIFFICULTY_DESIGN.yaml** — single `scaffold_difficulty_design:` key; 18 instances (2 per each of the 9 Difficulty Rules), all with structured `setup_api_calls`/`trigger`/`assert` chains and pre-computed literal expected values.
- **SCAFFOLD_CORNER_DESIGN.yaml** — single `scaffold_corner_design:` key; 47 active corner instances + 2 `excluded_because:` stubs across all nine guide sections (entities, state_machines, calculations, validations, endpoints, errors, roles, cross-cutting layers, consistency).

## Design highlights

- **Complexity profile**: temporal-windowing primary (category-exclusivity season grants + buffered suite-date bookings) over ledger-reconciliation secondary (installment schedule → invoices → payments → make-good credits); flat topology (peer collections + FK references), cyclic state machines, segregation-of-duties role model, immediate consistency. Season epoch advances via `POST /venues/{id}/advance-season` (ops-run checkpoint) — no wall-clock dependency.
- **Rule coverage mechanics**: dual-variant calcs on two domains (COMPOUND-vs-SIMPLE escalator fees on Contract; rate-card-vs-audited-CPM valuation on Deliverable/ValuationReport); combinatorial modes (b) installment per-line rounding with last-line remainder absorption (9,999,999 → 4,000,000/3,000,000/2,999,999) and (a) tiered make-good multiplier with `min()` season-fee cap (0.90/0.70 boundaries); depth-3 sponsor-BLOCK cascade (contract→deliverable→evidence) vs depth-2 advance-season auto-credit cascade; priority conflicts state-vs-fiscal and safety-vs-constraint; inclusive-season vs turnaround-buffered-date overlap semantics; pay+void and approve+redeem compensating invariants on receivable vs outstanding-credit quantities.
- **OCC**: two true-race rules (`expected_contract_version` on countersign, `expected_opportunity_version` on renewal counter), both wired as required inputs with version-bump side effects; all test chains capture versions from prior responses (no literals).

## Verification

`scaffold_lint.py` verdict (run verbatim):

```
Coverage
  §1.5 endpoints declared:    50
  §1.1 entities declared:     12
  §1.8 instances scanned:     18
  §1.9 instances scanned:     47
  Calls scanned (§1.8+§1.9):  711
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Additionally verified by hand/replay: instance-name uniqueness across both design files (67 unique), every error code triggerable and referenced by a validation row, enum-value closure, selector determinism (credit-redemption invoice selector pinned with tie-break and empty-pool error), `created_at`-only ordering (no id-based decisions), and call-by-call replay of the trickiest chains (stale-version 412 paths, contested-rights gating, season-close expiry ordering).

No sibling task directories were inspected — the scaffold was built purely from the scenario text plus the skill specification (skill `examples/` and `references/` were used only as format references, per the skill's own guidance).

Ready for Step 3 (copy INSTRUCTION.md) and Step 4 (PRD generation).

## Step 3: Copy Shared Files — 2026-08-14T00:29:00.000Z

Copied ./INSTRUCTION.md → tasks/task_1586_naming_rights_sponsorship_fulfillment/workspace/INSTRUCTION.md (1424 bytes).

## Step 4: Generate PRD — 2026-08-14T00:48:00.000Z

PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_1586_naming_rights_sponsorship_fulfillment/workspace/PRD.md` (~330 lines). The two withheld files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened.

**Document skeleton (domain-derived, not template-copied):**
- §1: 2-paragraph introduction (season-epoch + continuous-reconciliation framing)
- §2: 12 subsections — RBAC with per-role identity prose (SponsorContact entity-backed, four opaque roles), verbatim §2.2 envelope block, pagination, the season epoch, season/date overlap arithmetic, team/venue/league rights governance, monetary precision, derived receivable/make-good ledgers, cascade discipline, common resource properties, OCC, and the 10-tier validation pipeline
- §3: 8 subsections organized by business timeline (book-building → rights → contracting → activation → season close → evidence → billing → reporting/renewal), with all 50 state transitions, 9 calculations (tier boundaries, pinned installment split, per-line valuation rounding, buffer-day boundary cases), and all cross-entity cascades expressed in prose
- §4: 50-row endpoint table, 4 columns only; §5: 31-row error table, 2 columns only

**Hard Contract Reports:**

```
Field coverage check:
- entities[].fields: 66 required, 66 present, 0 missing
- endpoints[].request_body (+ OCC fields + payment response fields): 62 required, 62 present, 0 missing
- endpoints[].path_params: 13 required, 13 present, 0 missing
- query-param/filter names: all covered (overlap entity fields; reinforced in §4 intro)
Status: PASS

Rule coverage check:
- validations[] with priority: 10 tiers expressed in §2.12 with masking semantics + per-endpoint orderings in §3 (countersign, grant activate, deliverable create, evidence approve, invoice issue, credit approve/redeem, renewal create), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed in §2.11 (write endpoint + expected field + error id + 412), 0 missing
- state_machines[].transitions: 60 checked, 60 fully expressed (preconditions + error ids + side effects), 0 missing
- calculations[]: 9 checked, 9 fully expressed in precise prose (reconstruction-tested, no pseudocode), 0 missing
- validations[] conditions: 31 error ids all matchable to trigger prose in §2/§3, 0 missing
- endpoints[].side_effects / applies_to: all expressed (multi-endpoint scopes enumerated, e.g. CONTESTED gates exactly 3 operations), 0 missing
- entities[].fields[] structured content: defaults/initials/response shapes reconstructible from prose, 0 missing
- sibling-branch symmetry: all parallel branches (TERMINATE/EXPIRED/CANCEL/MISSED/MARK_WON/MARK_LOST/VOID paths, invoice re-derivation branches) rendered with equal density, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 512
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional checks: §2.2 emitted byte-verbatim from the canonical source file; no fuzzy/approximating words; no operator-syntax leaks outside backticks; all enum values and all transition action verbs present as exact strings; PRD ends at §5 with no audit footer.

## Step 5: Generate Unit Tests — 2026-08-14T01:12:00.000Z

All checks pass. Final state:

## Report

**Generated for `task_1586_naming_rights_sponsorship_fulfillment`:**

### Stage 1 — `test_helpers/` (9 files)
- `types.py` — 18 status/field enums + 13 TypedDicts (all 12 entities carry `id/created_at/updated_at/version`; `PaymentRecord` sub-type for invoice payments)
- `api_client.py` — `ApiClient(GenericApiClient)` with all 38 endpoint methods covering the 50-endpoint surface
- `api_errors.py` — all 31 `ApiErrorId` members with HTTP status map registered via `set_error_http_status_map`
- `assertions.py` — per-entity `assert_*` + financial invariant checker
- `factories.py` — 13 payload factories (input fields only)
- `constants.py` — initial epoch 2026, installment split 40/30/30, make-good tiers 0.90/0.70 with multipliers 1.00/1.25/1.50, 1-day suite turnaround buffer
- `test_users.py` — 4 opaque-role shared constants + per-instance builders; `make_sponsor_contact_headers(sponsor_id)` threads the entity-backed SponsorAccount id; `make_activation_headers(user_id)` supports the four-eyes reviewer split
- `fixtures.py` — composite helpers: venue/sponsor/asset creation, DRAFT→PROPOSE→COUNTERSIGNED→ACTIVE chain, grant/window activation, evidence submit/approve/reject with distinct submitter/reviewer ids, season advance, missed-deliverable-with-auto-credit setup, invoice issue/payment

### Stage 2 — `test_suite/` (conftest + 6 files, 83 tests)
- `test_01_envelope_rbac_and_basics.py` (11), `test_02_contract_lifecycle_and_occ.py` (10), `test_03_rights_windows_and_grants.py` (12), `test_04_deliverables_and_evidence.py` (16), `test_05_invoices_payments_credits.py` (16), `test_06_season_close_reports_renewals.py` (18)

### Coverage audit (machine-verified)
- **Difficulty (queue A): all 18/18 instances covered, each with ≥2 tests** (one instance has 4). Tags verified to resolve against `SCAFFOLD_DIFFICULTY_DESIGN.yaml`.
- **Corner (queue B): 45/47 non-stub instances covered with ≥1 test each.** The 2 `excluded_because:` stubs were not translated (cross-references verified to resolve). Two instances were **skipped per the PRD-first two-condition filter**:
  - `Corner/entities/contract_create_computed_field_input_ignored` — asserts the server silently ignores a client-supplied `scheduled_total_cents`, but PRD §2.12 tier 2 ("no undeclared fields") makes a 400 rejection equally faithful; outcome not uniquely derivable.
  - `Corner/validations/payment_void_twice_rejected` — asserts a second payment void fails `ERR_INVALID_STATE`, but no PRD sentence names an error or state gate for re-voiding; the void path is described only as compensation.

### Citation audit (machine-verified)
- All 83 tests: PRD citation greps verbatim against `workspace/PRD.md` (whitespace-normalized, markdown bold preserved), is rule-bearing, and each docstring ends with exactly one `Design: Difficulty/...` or `Design: Corner/...` line resolving to a real instance.
- No `pytest.mark.skip`/`skipif`/`xfail` anywhere; no scaffold references in comments/docstrings.
- `pytest --collect-only` collects 83 tests cleanly; `test_helpers` imports without errors; all files byte-compile.

## Step 6: Generate Implementation — 2026-08-14T01:12:00.000Z

Implementation complete and verified.

## Summary

Built a complete Python + Flask implementation of the Naming Rights & Sponsorship Fulfillment API at `/home/ubuntu/github/CodingPRD/tasks/task_1586_naming_rights_sponsorship_fulfillment/workspace/implementation/`:

- **`start.sh`** — executable launcher, guards `pip install` behind `import flask` so per-test reboots skip reinstall, `exec python3 app.py` in foreground, binds `0.0.0.0:$PORT` (default 10000)
- **`app.py`** — all 50 endpoints from the scaffold endpoint table, error handlers, route-level validation pipeline
- **`core.py`** — response envelope (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`; pagination fields `limit`/`offset`/`total_count`/`has_more`), full 31-code error catalog, `X-User-ID`/`X-User-Role` auth, request-shape validation (unknown fields, enums, int/date parsing), in-memory store, UUID/3-fractional-digit-UTC timestamp helpers
- **`domain.py`** — escalator fee calculations (COMPOUND/SIMPLE, single round-half-up per season via `Decimal`), pinned installment split (40%/30% rounded, remainder absorbed by POST_SEASON), tiered make-good formula (exact `Fraction` comparisons at 0.90/0.70, cap = season fee), receivable/outstanding/rights ledger recomputation, all cascades (sponsor BLOCK 3-hop, contract terminate, deliverable cancel → evidence void, league contest/release sweeps, advance-season checkpoint in the pinned deliverable → contract → rights-window order)

Key spec-fidelity decisions:
- Validation tiers ordered per PRD §2.12 (auth → shape → authz → existence → state → rights → temporal → constraint → referential → fiscal), with per-endpoint narrative orderings honored (e.g. deliverable create: CONTESTED → OUT_OF_TERM → CLOSED → WINDOW_INVALID → SUITE_CONFLICT → CONTRACT_NOT_ACTIVE → ASSET_NOT_AVAILABLE → INVALID_AMOUNT; evidence APPROVE: state → rights → SoD → over-delivery → deliverable-open)
- OCC on `expected_contract_version` (412 at countersign) and `expected_opportunity_version` (412 at counter), checked after the state gate
- `SponsorContact` entity-backed scoping: 403 on out-of-scope single reads, filtered lists; venue/asset/rights-window reads unscoped (no sponsor linkage)
- Every mutation (including cascaded ones) refreshes `updated_at` and bumps `version`; store starts completely empty on every boot

Verified: 54-check end-to-end smoke test (contract lifecycle, OCC, installment math 1236360/927270/927270 on a 3-season COMPOUND deal, payments/voids, season-close MISSED + auto make-good with 1.50x tier = 30000, credit cap/approve/redeem → COMPED, valuation report numbers, renewal counter/MARK_WON contract creation, sponsor BLOCK cascade) plus a second suite covering league preemption/contest/release reactivation, suite-night turnaround-buffer boundaries (checkout+1 conflicts, +2 allowed), pagination, and contract/grant expiry. Fresh boot reaches HTTP in ~750ms with empty state.

## Step 7: Run Tests and Iterate — 2026-08-14T01:20:00.000Z

Clean 8-round sweep: all rounds 83/83. Exiting.

## Summary

**Iterations run:** 2 (first sweep surfaced the failures; second sweep confirmed the fix across all 8 parallel rounds, 83/83 each).

**Failure signature:** 3 tests failed deterministically (identical in all 8 rounds of sweep 1), all in setup with `HTTP 422: ERR_INVALID_AMOUNT - avg_impressions_per_unit must be a positive integer`:
- `test_01_envelope_rbac_and_basics.py::TestPagination::test_asset_list_pagination_envelope`
- `test_04_deliverables_and_evidence.py::TestSuiteBookingTurnaroundBuffer::test_checkin_on_buffer_day_conflicts`
- `test_04_deliverables_and_evidence.py::TestSuiteBookingTurnaroundBuffer::test_checkin_two_days_after_checkout_allowed`

**Diagnosis (STEP 2 — test bug):** All three tests' setup paths registered a `HOSPITALITY` asset with `avg_impressions_per_unit=0, cpm_cents=0`. PRD §3.1 states verbatim: "These rate and fee fields must be positive integers (`ERR_INVALID_AMOUNT`)" — covering all of `rate_card_unit_cents`, `avg_impressions_per_unit`, and `cpm_cents` with no per-`asset_class` exemption. The implementation's rejection was PRD-faithful; the test setups violated a PRD precondition. The asserted rules themselves (§2.3 pagination envelope; §2.5 suite turnaround buffer) are PRD verbatim-covered, so the tests stayed.

**Tests deleted:** none.

**Fixes applied to `test_helpers/`:** none (the offending values were inline overrides in the test functions, not in shared fixtures/factories).

**Fixes applied to `test_suite/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1586_naming_rights_sponsorship_fulfillment/test_suite/test_01_envelope_rbac_and_basics.py` (line ~110): asset `A3` setup override changed `avg_impressions_per_unit=0, cpm_cents=0` → `=1, =1` — makes setup satisfy PRD §3.1 positivity.
- `/home/ubuntu/github/CodingPRD/tasks/task_1586_naming_rights_sponsorship_fulfillment/test_suite/test_04_deliverables_and_evidence.py` (line ~99, `_setup_suite`): same change — `avg_impressions_per_unit=0, cpm_cents=0` → `=1, =1`.

**Fixes applied to `implementation/`:** none — the positivity check was correct and was preserved per the cardinal rule against stripping PRD-required checks to accommodate non-faithful fixtures.

## Step 8: Finalize PRD — 2026-08-14T01:25:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1586_naming_rights_sponsorship_fulfillment/workspace/PRD_FINALIZED.md` created as a byte-identical copy of `PRD.md` — zero edits were warranted.

## Line counts / delta
- `PRD.md`: 303 lines; `PRD_FINALIZED.md`: 303 lines — 0.0% delta (byte-identical, verified with `diff -q`).

## Per-item disposition (no changes made)

- **§3.1 asset rate/fee positivity (`test_01_envelope_rbac_and_basics.py` ~line 110 fix)** — no edit — PRD already pins behavior verbatim; pure test-fixture bug. PRD §3.1 states "These rate and fee fields must be positive integers (`ERR_INVALID_AMOUNT`)" immediately after enumerating `rate_card_unit_cents`, `avg_impressions_per_unit`, and `cpm_cents`, with no per-`asset_class` exemption. The implementation enforces exactly this: `implementation/app.py:191-193` rejects any of the three fields `<= 0` with `ERR_INVALID_AMOUNT` for all asset classes (the `HOSPITALITY` asset with `avg_impressions_per_unit=0, cpm_cents=0` was correctly rejected). The asserted rule in the failing test (§2.3 pagination envelope) is PRD verbatim-covered.
- **§3.1 asset rate/fee positivity (`test_04_deliverables_and_evidence.py` ~line 99 `_setup_suite` fix)** — no edit — same reasoning; same implementation site (`app.py:191-193`). The asserted rule (§2.5 suite turnaround buffer arithmetic) is PRD verbatim-covered.
- **Implementation fixes / test deletions / test_helpers fixes** — none in the step_7_diff, so nothing to trace.

## Pre-edit search log

Since no edits were committed, the mandatory per-edit enumeration was applied to the *candidate* edit (tightening §3.1's positivity sentence) and rejected as unnecessary:

- **(a) Subject:** positivity validation of the asset valuation fields (`rate_card_unit_cents`, `avg_impressions_per_unit`, `cpm_cents`) at asset registration.
- **(b) Impl paths enumerated:** `implementation/app.py:183-200` (asset creation — shape validation requires all three fields for every `asset_class`, then lines 191-193 uniformly reject `<= 0`); `implementation/app.py:1024-1026` and `implementation/domain.py:25` (only other usages of these fields — valuation-report and make-good computations that consume stored values, no validation); full `ERR_INVALID_AMOUNT` sweep (`app.py` lines 193, 339, 341, 622, 685, 785, 834, 954, 1117, 1208) — every site maps to a PRD-verbatim positivity statement in §3.1, §3.3, §3.4, §3.5, §3.6, §3.7, §3.8.
- **(c) Wording adjustment:** none — the existing sentence "These rate and fee fields must be positive integers" is a universal claim over the three just-enumerated fields with no asset-class exemption, which is exactly what every enumerated impl path exhibits. Adding or changing wording would risk a new mismatch with zero recoverable ambiguity gained.

**Conclusion:** every `<step_7_diff>` item is a pure test-fixture bug where PRD.md already uniquely determines the implementation's behavior. `PRD_FINALIZED.md` is a byte-identical copy of `PRD.md`, and a fresh implementer reading it would reproduce the implementation's behavior at all step_7 sites.

## Step 9: Complete PRD — 2026-08-14T01:40:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1586_naming_rights_sponsorship_fulfillment/workspace/PRD_COMPLETED.md` written as a minimal patch over `PRD_FINALIZED.md` (PRD_FINALIZED.md existed, so it was the source).

**Size:** 303 → 304 lines; 52,342 → 54,894 chars (+2,552 chars; 39 diff lines).

**Counts:** 17 ambiguity-pins, 2 mismatch-revisions (19 changes total).

**Changes (section — insert|revise — ambiguity|mismatch — what — impl ref):**

- §2.1 — revise — mismatch — sponsor-contact read scope: single-resource out-of-scope reads (incl. the sponsor account itself) get `ERR_FORBIDDEN`, list endpoints filter instead of rejecting, and venues/assets/rights-windows carry no sponsor scoping at all — app.py:86-91 (get_venue), 124-131 (get_sponsor), 203-209 (get_asset), 263-269 (get_window) vs. scoped getters (e.g. app.py:356-363)
- §2.3 — insert — ambiguity — non-integer/out-of-range `limit` (1–100) or negative `offset` → `ERR_INVALID_REQUEST` — core.py:281-296
- §2.3 — insert — ambiguity — `total_count` = filtered match count; `has_more` ⟺ `offset` + returned records < `total_count` — core.py:170-176, 299-306
- §2.10 — revise — ambiguity — `version` starts at 1 on creation; `updated_at` initially equals `created_at` — core.py:205-214
- §2.12 tier 2 — insert — ambiguity — non-JSON-object body rejected; absent body treated as empty object — core.py:240-246
- §2.12 tier 4 — revise — ambiguity — added `renewed_from_contract_id` to body references; multiple body refs validated in the order named — app.py:327-329, 583-588, 780-783
- §3.2 — insert — ambiguity — rights-window creation applies no `first_season ≤ last_season` ordering check — app.py:245-260
- §3.2 — insert — ambiguity — grant creation's only window check is term containment; span ordering not validated — app.py:488-490
- §3.3 — revise — ambiguity — PATCH applies supplied values without re-running creation-time term-window/amount validations — app.py:390-396
- §3.5 — insert — ambiguity — each advance-season phase processes its records in `created_at` ascending order — domain.py:180-182, 197-198, 206-207
- §3.5 — revise — ambiguity — manual credit requires only existing references + positive amount; deliverable need not be `MISSED` nor belong to the named contract; new credits carry `approved_amount_cents`/`redeemed_against_invoice_id` unset — app.py:773-792
- §3.6 — insert — ambiguity — new evidence submission starts with `review_note` unset — app.py:686-691
- §3.6 — revise — ambiguity — `evidence_uri` optional on RESUBMIT; omitted → previous value retained — app.py:761-762
- §3.7 — insert — ambiguity — payment-void preconditions: invoice must be `ISSUED`/`PARTIALLY_PAID`/`PAID`, payment not already voided (both `ERR_INVALID_STATE`); unknown `payment_id` → `ERR_NOT_FOUND` — app.py:979-985
- §3.8 — insert — ambiguity — empty reportable deliverable set → monetary measures 0 and `fulfillment_pct` 0.0 — app.py:1034-1039
- §3.8 — insert — ambiguity — new opportunity starts with `resulting_contract_id` unset — app.py:1118-1121
- §3.8 — revise — ambiguity — MARK_WON renewal contract also copies `title` from source — app.py:1150-1152
- §3.8 — insert — ambiguity — counter guard order: stage legality → version freshness → fee positivity — app.py:1203-1208
- §4 — insert — ambiguity — advance-season and payment-void declare no request fields; any supplied field is undeclared (`ERR_INVALID_REQUEST`) — app.py:98, 974
- §5 — revise — mismatch — added `ERR_INTERNAL` (500) row to the catalogue and pinned that undefined paths / unsupported methods return `ERR_NOT_FOUND` (404) — app.py:38-50

Everything else in the implementation (all endpoint routes, state machines, fee/escalator/make-good/installment formulas, validation pipeline order per endpoint, cascades, ledger recomputation, response envelopes and field shapes, created_at ordering) was already uniquely pinned by the PRD and left untouched.
