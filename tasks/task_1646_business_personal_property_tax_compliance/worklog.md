# Worklog — task_1646_business_personal_property_tax_compliance

## Step 1: Create Task Directory — 2026-08-14T04:27:47.281Z

Task directory `tasks/task_1646_business_personal_property_tax_compliance/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline dispatcher; Step 1 treated as DONE per invocation contract (no index scan, no other task_* directory touched).

Difficulty directive from user: "Generate task hard than expert level!" — forwarded to the scaffold-generator subagent as a directive to target the Expert band's upper boundary (§0.4) with maximal difficulty layering (§0.2) and tightest entity coupling.

## Step 2: Generate Scaffold — 2026-08-14T05:23:50Z

All checks pass. The scaffold package for task 1646 is complete and lint-clean.

## Summary

**Output files** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1646_business_personal_property_tax_compliance/`):
- `SCAFFOLD.yaml` — §1.0–§1.7 only (response envelope verbatim; no design keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level `scaffold_difficulty_design:` key
- `SCAFFOLD_CORNER_DESIGN.yaml` — single top-level `scaffold_corner_design:` key

**Counts:**
- Entities: **15** (ClientAccount, Operator, Jurisdiction, JurisdictionClassRule, Asset, DisposalRecord, Rendition, FilingExtension, AssessmentNotice, Appeal, TaxBill, ExemptionApplication, AbatementAgreement, AccrualForecast, AuditEvent)
- Endpoints: **56** — above the ~32 guideline for a structural reason: lint check (f) forces a reverse-reachability GET for each of 12 FK-bearing children, and testability-completeness forces ~22 action endpoints for 12 state machines. Surface is dense, not padded (no entity was added for count; the scenario's 8 workflow streams all map to live mechanics)
- Error codes: **29** (within the 28–30 target)
- State machines: **12** blocks covering 10 entities — cyclic (Rendition amendment loop, Exemption suspend/reinstate, Abatement recertification), branching fork-join (Appeal DECIDED→{ACCEPTED, ESCALATED}→CLOSED with divergent cascades), parallel dimensions (Asset lifecycle × classification; TaxBill validation × payment)
- Calculations: **6** — depreciation (dual-variant FULL_YEAR/HALF_YEAR), per-line-rounding rendition aggregation, tiered/capped late penalty, evaluation-order-pinned bill validation (exemption cap), dual-variant accrual forecast (NOTICE_BASED 64000 vs RENDERED_CONSERVATIVE 70400 on identical data), installment waterfall split
- §1.8 instances: **19** (9 rules × 2, plus a 3rd combinatorial_formula instance covering modes a/b/c; every differentiation clause honored — verified by a mechanical grounds-resolvability audit)
- §1.9 instances: **44 non-stub / 15 stub** (stubs cite only §1.8 instance names, verified to resolve)
- Difficulty layers applied: **4** — optimistic_concurrency (extension supersede on Rendition.version; forecast supersede on ClientAccount.version, both true CREATE-with-supersede races), cascading_side_effects (disposal→line→rendition→forecast depth-4; appeal→notice→bill→installment depth-3; abatement clawback), dual_variant_calculation, scheduled_actions (monotonic logical clock, default 2026-08-01T00:00:00Z, five pinned sweeps)
- Role model: segregation_of_duties (filer ≠ amender; bill importer ≠ validator) over entity_backed Operators

**Validation:** `scaffold_lint.py` verdict, verbatim:

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

(625 calls scanned; 19 §1.8 + 44 active §1.9 instances; 56 endpoints; 15 entities.)

**Quality Checklist: passed.** Mechanically verified beyond the linter: enum-value closure (all 60 enum values have a producing transition/init; caught and fixed a dead `DENIED` extension state), all 29 errors exercised by at least one design instance, instance names unique across both design files, stub citations resolve, forbidden concurrency vocabulary absent, roles/endpoints mutually consistent, all formula-derived asserts precomputed with pinned literals (rounding, caps, day counts, splits verified by code), clock monotonicity respected in every recipe (no fixture date precedes the 2026-08-01 default), and every `${var}` traces to a declared capture. Two design bugs were found and fixed during generation: a value-vs-tax unit mismatch in the exemption/abatement credit formula (fixed with prorated line-share `V_line` and non-negative clamps) and a SoD rule that was vacuous until SeniorManager was added to the file/import endpoint roles.

## Step 3: Copy Shared Files — 2026-08-14T05:23:50Z

Copied ./INSTRUCTION.md → tasks/task_1646_business_personal_property_tax_compliance/workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-08-14T05:45:51Z

Done. The PRD is written to `/home/ubuntu/github/CodingPRD/tasks/task_1646_business_personal_property_tax_compliance/workspace/PRD.md` (the two forbidden design files were never opened; no sibling tasks were read).

## Summary

**PRD section list:**
- §1. Introduction (2 paragraphs — business context + system framing)
- §2. Global Specifications & System-Wide Principles
  - 2.1 User and Role-Based Access Control (all 5 roles, exact spellings, per-role identity prose: `TaxAnalyst`/`SeniorManager` entity-backed by `Operator`, `Client` entity-backed by `ClientAccount`, `FirmAdmin`/`AssessorClerk` opaque)
  - 2.2 API Response Structure — **byte-identical** to the canonical verbatim block (verified by diff)
  - 2.3 Pagination (`limit` default 10 / min 1 / max 100, `offset` default 0, `created_at` ascending, meta fields)
  - 2.4 Resource Identity, Timestamps, and Nested Retrieval (incl. AuditEvent `common_fields: false` exception; left-to-right `ERR_NOT_FOUND`)
  - 2.5 The Logical Clock and Deterministic Compliance Sweeps (startup default 2026-08-01T00:00:00Z, monotonicity, pinned 5-stage sweep order)
  - 2.6 Monetary Precision, Rounding Order, and Aggregation Discipline (whole cents, round-half-up, line-first aggregation, per-step rounding)
  - 2.7 Optimistic Concurrency Control (both OCC rules: `expected_rendition_version` on extensions, `expected_client_version` on forecast publish, `ERR_STALE_VERSION`/412)
  - 2.8 Segregation of Duties (amendment vs. `filed_by_operator_id`; validation vs. `created_by_operator_id`)
  - 2.9 Validation Order and Error Precedence (all 29 validations in priority order with error IDs, plus worked precedence examples)
  - 2.10 The Client Audit Trail (all 21 `event_type` values, `actor_id` "system" convention)
- §3. Business Logic & Workflows (8 subsections: 3.1 onboarding/jurisdiction config, 3.2 asset intake/classification, 3.3 disposals/reversal/reconciliation, 3.4 rendition assembly/filing/extensions/amendments, 3.5 notices/appeals/finalization cascade, 3.6 bill validation/payment scheduling, 3.7 exemptions/abatements, 3.8 forecasts/staleness)
- §4. Endpoint Definitions (56 endpoints, 4 columns only)
- §5. Error Code Catalogue (29 error codes, 2 columns only)

**Size:** 333 lines, 9,037 words.

**Hard Contract Reports:**

```
Field coverage check:
- entities[].fields: 109 required, 109 present, 0 missing
- endpoints[].request_body / input-only identifiers: 12 required, 12 present, 0 missing
- endpoints[].query_params: 20 required, 20 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 29 checked, 29 expressed in fixed-order prose (§2.9 + workflow text), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write capability + occ field + ERR_STALE_VERSION/412 all named), 0 missing
- state_machines[].transitions: all transitions across the 10 machines checked and fully expressed (from/to states, preconditions with error IDs, side-effect cascades incl. the divergent ACCEPT vs ESCALATE fork and the asymmetric sweep-vs-protest notice finalization branches), 0 missing
- calculations[]: 6 checked, 6 fully expressed in precise prose (asset_depreciation FULL_YEAR/HALF_YEAR with July-1 cutoff, rendition_total_aggregation line-first rounding + line ordering, late_filing_penalty with TAX_BASE nested rounding, tax_bill_validation pinned 4-step order with 50% cap and 100-cent tolerance, accrual_forecast both variants with 10% uplift, installment_split with first-installment remainder), 0 missing
- validations[] conditions: 29 checked, 29 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 56 checked, 56 expressed, 0 missing
- entities[].fields[] structured content: all defaults, initial values, nullability, and enum constraints reconstructible from prose, 0 missing
- sibling-branch symmetry: 8 parallel groups checked (MATCHED/DISCREPANCY, ACCEPT/ESCALATE, both close branches, both depreciation conventions, both forecast variants, both penalty bases, OPEN/WITHDRAW, SUSPEND/REINSTATE), all with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 636
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional scans: no fuzzy/approximating words, no pseudocode operator tokens (`==`, `ceil(`, `min(`, etc.) outside fences, all 29 error IDs mentioned in §2/§3 prose, all enum/state values present in backticks, all 21 audit event types listed, and the document ends at §5 with no audit footer.

## Step 5: Generate Unit Tests — 2026-08-14T06:18:54Z

Generation complete. Summary:

## Deliverables

**test_helpers/** (9 modules, all under `/home/ubuntu/github/CodingPRD/tasks/task_1646_business_personal_property_tax_compliance/test_helpers/`):
- `types.py` — status enums + TypedDicts for all 15 entities (AuditEvent correctly omits `updated_at`/`version` per PRD §2.4)
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per each of the 56 PRD endpoints
- `api_errors.py` — `ApiErrorId` enum (30 codes) + HTTP status map registered via `set_error_http_status_map`
- `assertions.py` — per-entity assertions, `find_rendition_line`/`find_installment` helpers, `assert_date_is` (date-part comparison, serialization-agnostic), `assert_bill_allocation_invariant`
- `factories.py` — input-field-only payload factories
- `constants.py` — PRD thresholds (variance tolerance 100, exemption tax cap 50%, uplift 10%, 30-day penalty month, 90-day cure, default logical clock)
- `test_users.py` — opaque shared constants for FirmAdmin/AssessorClerk + per-instance builders for entity-backed TaxAnalyst/SeniorManager/Client
- `fixtures.py` — composite builders: `setup_classified_asset`, `setup_draft_rendition`, `setup_filed_rendition`, `setup_notice_for_filed`, `setup_validated_bill`, `setup_decided_appeal`, `setup_approved_exemption`, `setup_abated_asset`, OCC-aware `publish_forecast`, `set_logical_clock`
- `__init__.py` — barrel export

**test_suite/** (10 test files + `conftest.py`, 81 tests total):
- Queue A (§1.8 Difficulty): **38 tests** — all 19 instances covered with exactly 2 tests each
- Queue B (§1.9 Corner): **43 tests** — 43 of 44 non-stub instances covered with ≥1 test each

## Skipped instance (1)
- `Corner/entities/rendition_create_computed_input_ignored` — fails the PRD-first filter: no PRD sentence states that client-supplied values for computed fields are ignored on creation; a PRD-faithful implementer could equally reject the unknown field with `ERR_INVALID_REQUEST` (two-reader failure). Gap left as a gap; no placeholder emitted.

## Sub-assertion adjudications (PRD not uniquely pinning a value)
- Initial `version` absolute value (PRD says only "an integer the server increments on every mutation") — asserted as `int` type, never `== 1`; version *increments of exactly one* are asserted where PRD states "increments by one" (extension grant, forecast publish, disposal cascade)
- `updated_at` "strictly later" on the disposal cascade — asserted presence/format only (millisecond-tie flakiness risk); the load-bearing claims (total 600000→0, version +1) are fully asserted
- `deadline_date`/installment `due_date`/`suspended_date` asserted by calendar-date prefix, since PRD pins the date, not the serialization format
- Pre-filing lateness fields asserted falsy (`None`/`0`/`False`) rather than pinned to zero

## Verification
- Automated audit: 0 problems — every test docstring ends with exactly one `Design: Difficulty/<rule_id>/<name>` or `Design: Corner/<section>/<name>` line resolving to a real instance; every ≥8-word quoted fragment greps verbatim in PRD.md; all 15 `excluded_because` stub pointers resolve; no stub translated; no skip/skipif/xfail anywhere; no scaffold references in comments/docstrings
- All 10 test modules import cleanly and `pytest --collect-only` collects exactly 81 tests

## Step 6: Generate Implementation — 2026-08-14T06:18:54Z

Done. The implementation is complete and verified.

## Summary

**Task 1646 — Business Personal Property Tax Compliance** — full Python + Flask implementation at `/home/ubuntu/github/CodingPRD/tasks/task_1646_business_personal_property_tax_compliance/workspace/implementation/`.

**Files (2,980 lines total):**
- `start.sh` (10) — foreground launcher; guarded `pip install` (no-op once Flask importable), `exec python3 app.py`
- `requirements.txt` (1)
- `app.py` (64) — app factory, error handlers, route registration, `0.0.0.0:$PORT`
- `db.py` (60) — `Store` class: 15 in-memory dicts keyed by id + logical clock starting at `2026-08-01T00:00:00Z`
- `errors.py` (47) — `ApiError` + all 30 error-id constants with HTTP statuses
- `response.py` (55) — envelope helpers (`meta`/`response_type`/`data`; pagination in meta)
- `middleware.py` (67) — `X-User-ID`/`X-User-Role` auth, entity-backed resolution, role checks, pagination parsing
- `util.py` (151) — body/date validation, `Decimal` ROUND_HALF_UP, common-field stamping
- `services.py` (565) — all 6 calculations, disposal/finalization/termination cascades, forecast flagging (covered vs force variants), the 5-stage clock sweep
- `serializers.py` (268) — wire views for all 15 entity types (audit events without `updated_at`/`version`)
- `routes_admin.py`, `routes_assets.py`, `routes_renditions.py`, `routes_notices_appeals.py`, `routes_bills.py`, `routes_incentives.py` — 56 endpoints

**Endpoint count:** 56 (matches the scaffold endpoint table exactly).

**State storage:** purely in-memory Python dicts on a per-process `Store()`; no SQLite, no disk files, no seeding. Verified fresh reboot via `start.sh` yields `total_count: 0`.

**Verification performed (smoke tests across 6 scenarios on throwaway ports, all killed afterward):**
- Full pipeline: client/operator/jurisdiction/class-rule/asset/classify/rendition/generate-lines/file/notice/accept/bill/validate/schedule/pay/forecast/audit
- Calculations verified numerically: FULL_YEAR and HALF_YEAR depreciation, VALUE_BASE and TAX_BASE late penalties (e.g. 108 days → 4 months → 20% → 12000), bill validation with exemption credit (6000) + abatement credit (4000) + late component (200000) = 210000, installment split remainder-to-first (4468/4466/4466), both forecast variants
- Validation priority order observed: OCC (12) before extension window (16); auth before forbidden; stale version → 412, etc.
- Segregation of duties on amendments and bill validation; client FK-chain ownership on resolve/pay
- Clock sweeps: extension EXPIRED, notice auto-finalization, installment LATE → DELINQUENT, exemption cure REVOKED after 90 days
- Disposal cascade (line exclusion, total recompute, forecast flag) and reverse (line reinstatement); RECONCILED on filing
- Appeal fork-join: ACCEPT and ESCALATE→board-close both finalize the notice and revalidate bills; audit event order NOTICE_FINALIZED before APPEAL_RESOLVED
- Amendment OPEN/WITHDRAW with filed-snapshot restoration; forecast staleness distinction between first filing (skips already-covering forecasts) and amendment re-filing (flags all)

`bash start.sh` boots cleanly and serves HTTP within ~3 seconds.

## Step 7: Run Tests & Fix Loop — 2026-08-14

Ran the 8-round parallel stability sweep (`prd-bench-local-run --isolation per-test-server --timeout 120 --test-timeout 30`, all 8 rounds concurrent, `wait`-joined).

**Result: clean on iteration 1.** All 8 rounds report `passed=81, failed=0, total=81`. Union of failing tests across rounds is empty — no flakiness surfaced, no diagnostic protocol steps triggered, zero deletions, zero fixes to `test_helpers/` or `implementation/`. Diagnostic `results.*.json` artifacts removed after verification (a fresh 8-round sweep was re-run afterwards by the orchestrator to leave the final passing `results.1..8.json` artifacts in place).

## Step 8: Finalize PRD — 2026-08-14T06:25:00Z

SKIPPED per the skip condition: Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes. `PRD.md` already determined every behavior the implementation exhibits, so no `PRD_FINALIZED.md` was produced.

## Step 9: Complete PRD — 2026-08-14T06:38:36Z

All 22 edits landed across 21 lines (two edits share the §3.4 filing paragraph). Line count unchanged at 333; all edits are in-paragraph inserts/revisions. §4 endpoint table (56 rows) and §5 error table untouched; no bare method/path tokens introduced into §3 prose.

## Summary

**Source vs output:** `PRD.md` 333 lines / 66,070 chars → `PRD_COMPLETED.md` 333 lines / 69,946 chars (char-delta **+3,876**, zero lines added/removed — all edits inline).

**Counts:** 18 ambiguity-pins, 4 mismatch-revisions (22 edits total).

**Changes** (impl paths relative to `/home/ubuntu/github/CodingPRD/tasks/task_1646_business_personal_property_tax_compliance/workspace/implementation/`):

- §2.1 — insert — ambiguity — header-role resolution requires only that the id name an existing Operator; no cross-check of header role vs stored `operator_role` — middleware.py:30-32
- §2.3 — insert — ambiguity — non-integer limit/offset, limit outside 1–100, or negative offset → `ERR_INVALID_REQUEST` — middleware.py:49-66
- §2.4 — insert — ambiguity — body-carried identifiers (`client_id`, `jurisdiction_id`) resolve after field-level body validation, before uniqueness/business rules, and 404 on failure — routes_assets.py:41-47, routes_renditions.py:37-47, routes_admin.py:261-266
- §2.5 — revise — mismatch — automatic sweep transitions append audit events only where a §2.10 event type exists (NOTICE_FINALIZED, INSTALLMENT_LATE, EXEMPTION_REVOKED, actor "system"); extension expiry and RECERTIFICATION_DUE append nothing — services.py:505-511, 539-545 vs 514-536, 547-562
- §2.9 rule 2 — insert — ambiguity — Client ownership half of authorization is evaluated after existence (rule 3) and body (rule 4), since the chain needs the resource — routes_notices_appeals.py:214-224, routes_bills.py:195-202
- §2.9 rule 4 — insert — ambiguity — `claimed_value_cents` and `decided_value_cents` must be at least zero — routes_notices_appeals.py:104, 190
- §3.1 — revise — mismatch — `state_code` has no two-letter/format enforcement (dropped "two-letter") — routes_admin.py:193 (req_str only)
- §3.1 — insert — ambiguity — `max_extension_days`, `late_penalty_pct_per_month`, `max_late_penalty_pct`, `percent_good_floor_pct`, `de_minimis_line_cents` must be non-negative integers; `percent_good_vector` non-empty int array; violations → `ERR_INVALID_REQUEST` — routes_admin.py:197-208, 252-259
- §3.2 — revise — ambiguity — `include_disposed` counts as set for `true`/`1`/`yes` case-insensitively; anything else unset — routes_assets.py:97-99
- §3.3 — insert — ambiguity — disposal recording gated on asset `ACTIVE`; recording on `DISPOSED` → `ERR_INVALID_STATE_TRANSITION` — routes_assets.py:142-143
- §3.4 — insert — ambiguity — exclusion-reason precedence when several hold: DISPOSED, then DEMINIMIS, then NON_TAXABLE — services.py:98-114
- §3.4 — revise — ambiguity — never-generated lines fail filing with `ERR_EMPTY_RENDITION`; filing from any status other than DRAFT/AMENDMENT_OPEN (incl. ACCEPTED) → `ERR_RENDITION_ALREADY_FILED` — routes_renditions.py:138-142, 159-160
- §3.4 — insert — ambiguity — `filed_at` records the logical clock instant, not wall-clock time — routes_renditions.py:165 (`store.clock_iso()`)
- §3.4 — revise — ambiguity — amendment WITHDRAW also restores the `lines` array from the filed snapshot — routes_renditions.py:239-246
- §3.4 — insert — ambiguity — no lower bound on `requested_extend_to_date`: it may precede the base deadline or clock date, yielding zero/negative `granted_days` and a backward-moving deadline — routes_renditions.py:286-295, 313
- §3.5 — insert — ambiguity — GRANTED_REDUCTION/DENIED value-rule violations → `ERR_INVALID_REQUEST`, checked after the appeal status gate — routes_notices_appeals.py:191-200
- §3.5 — insert — ambiguity — missing/non-positive `board_value_cents` → `ERR_INVALID_REQUEST`, evaluated after the ESCALATED status gate — routes_notices_appeals.py:282-288
- §3.6 — revise — mismatch — bill-validation line share uses the rendition's *current* line set (not "the line from the last filing"), and a zero rendition total yields a zero line share — services.py:220-226, 246
- §3.6 — revise — mismatch — schedule-cancel recomputes payment status via the pinned derivation, which lands on `PAID` (not `PARTIALLY_PAID`) when paid installments already cover the validated amount — routes_bills.py:175-180, services.py:314-333
- §3.6 — insert — ambiguity — an `installment_no` matching no installment → `ERR_INVALID_REQUEST` — routes_bills.py:203-209
- §3.7 — insert — ambiguity — recertify `tax_year` ≠ `last_recertified_year`+1 → `ERR_INVALID_REQUEST`, checked after the RECERTIFICATION_DUE status gate — routes_incentives.py:246-251
- §3.8 — insert — ambiguity — re-flagging an already-flagged forecast repeats version bump + event under every staleness trigger *except* notice finalization (sweep or appeal resolution), which leaves it untouched — services.py:403-422 (`flag_forecasts` skip-if-flagged) vs 425-463 (force/uncovered variants)

Output file: `/home/ubuntu/github/CodingPRD/tasks/task_1646_business_personal_property_tax_compliance/workspace/PRD_COMPLETED.md`.
