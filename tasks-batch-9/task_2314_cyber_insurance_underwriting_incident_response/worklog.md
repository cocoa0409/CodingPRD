# Worklog — task_2314_cyber_insurance_underwriting_incident_response

## Step 1: Create task directory — 2026-09-01T15:23:25.658Z

Created `tasks/task_2314_cyber_insurance_underwriting_incident_response/` and its `workspace/` subdirectory. Directory name was pre-allocated by the caller (no index scan performed).

## Step 2: Generate scaffold — 2026-09-01T17:11:40.000Z

Generation complete. All three artifacts are written and the lint is clean.

**Files** (all under `/home/ubuntu/github/CodingPRD/tasks/task_2314_cyber_insurance_underwriting_incident_response/`):
- `SCAFFOLD.yaml` (§1.0–§1.7, 2623 lines)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single key `scaffold_difficulty_design`, §1.8)
- `SCAFFOLD_CORNER_DESIGN.yaml` (single key `scaffold_corner_design`, §1.9)

**Scaffold shape** — domain `cyber-insurance-underwriting-incident-response`, prefix `/cyber`; complexity profile: primary `quota_allocation`, secondary `compliance_audit`, layers `[optimistic_concurrency, cascading_side_effects, dual_variant_calculation, selector_policy]`, flat topology, parallel state-machine shape, `segregation_of_duties` role model, `immediate` consistency.

- **14 entities**: ControlRequirement, InsuredAccount, Application, ControlAttestation, ExternalScan, Policy, CoverageSection, PanelVendor, IncidentClaim, VendorEngagement, ProofOfLoss, ClaimPayment, RenewalAssessment, SystemicEventScenario.
- **10 state machines** (Application.status, ExternalScan, Policy.lifecycle_status + Policy.limit_status as independent dimensions, IncidentClaim, VendorEngagement, ProofOfLoss, ClaimPayment, RenewalAssessment, SystemicEventScenario).
- **4 optimistic-concurrency rules** (quote, bind, proof submission, renewal quote), **9 calculations** (control_posture_score and bi_indemnity_quantification are the dual-variant pair; premium_quote, tower_allocation_waterfall, policy_loss_ratio, renewal_premium_adjustment, panel_vendor_selection, engagement_incurred_amount, systemic_aggregation_model), **15 prioritised validations**, **66 endpoints (32 GET)**, **51 errors**, **5 roles**.

**Difficulty design (§1.8)**: 9 rules × 19 instances (dual_variant_calc 2, combinatorial_formula 3, non_linear_state_machine 2, transitive_cascade 2, priority_pair_validation_conflict 2, boundary_precision_check 2, cross_entity_state_dependency 2, resource_temporal_overlap 2, compensating_invariant 2), each with structured `setup_api_calls`, pre-computed literal asserts, and `${...}`-bearing expected-version payloads.

**Corner design (§1.9)**: all 9 sections, **143 instances** — entities 22, state_machines 35, calculations 22, validations 22, endpoints 10, errors 12, rbac 11, cross_cutting_complexity_layers 8, consistency_model 1. 124 carry full test recipes; 19 are `excluded_because` stubs, each citing an existing §1.8 instance by name.

**Verification**: no name collisions across the 162 §1.8+§1.9 instances; every stub reference resolves; all 51 error ids are triggerable by at least one recipe. Consistency repairs made to SCAFFOLD.yaml along the way: `per_record_notification_rate_usd` made optional on POST /cyber/panel-vendors (it has default 0.00), and five flat child reads added for FK reverse-reachability (`GET /cyber/control-attestations` + `/{attestation_id}`, `GET /cyber/external-scans`, `GET /cyber/coverage-sections` + `/{section_id}`), with the Insured role note updated to keep §1.7 self-consistent.

Final lint verdict, verbatim:

```
Coverage
  §1.5 endpoints declared:    66
  §1.1 entities declared:     14
  §1.8 instances scanned:     19
  §1.9 instances scanned:     124
  Calls scanned (§1.8+§1.9):  2728

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Step 3: Copy shared files — 2026-09-01T17:12:35.838Z

Copied project-root `INSTRUCTION.md` (1424 bytes) to `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-01T17:30:10.162Z

PRD generation is complete.

**Step 4: Generate PRD — output written to `/home/auubuntu/…` (corrected path below)**

`/home/ubuntu/github/CodingPRD/tasks/task_2314_cyber_insurance_underwriting_incident_response/workspace/PRD.md` — **522 lines, 14,269 words**.

**Section structure**

- `# Cyber Insurance Underwriting & Incident Response API — Product Requirements Document`
- **§1. Introduction** — 3 paragraphs, business-pain framing (four disconnected systems), scope, and two design commitments (money/capacity conservation, segregation of duties).
- **§2. Global Specifications & System-Wide Principles** — 11 subsections: 2.1 User and Role-Based Access Control; 2.2 API Response Structure (verbatim fixed block, byte-identical); 2.3 Pagination; 2.4 Record Identity, Audit Fields, and the Immutable Catalog; 2.5 The Logical Clock and Epoch Processing; 2.6 Monetary Values, Ratios, and Rounding Discipline; 2.7 Stale-Read Protection on Quotes, Bindings, Proofs, and Renewals; 2.8 Cascade Discipline; 2.9 Path Resolution Order; 2.10 Validation Precedence (all 15 priorities in order); 2.11 Segregation of Duties.
- **§3. Business Logic & Workflows** — 9 subsections following the business timeline: 3.1 The Underwriting Control Catalog; 3.2 From Applicant to Submitted Application; 3.3 External Scanning and the Verification Cascade; 3.4 Posture Scoring and Premium Construction; 3.5 Quoting, Declining, Binding, and the Coverage Tower; 3.6 Warranty Reporting, Incident Notification, and Coverage Confirmation; 3.7 The Response Panel: Empanelment, Selection, and Deployment; 3.8 Proof of Loss, Indemnity Quantification, Allocation, and Reversal; 3.9 Renewal Conditions, Premium Adjustment, and Portfolio Aggregation.
- **§4. Endpoint Definitions** — status-code paragraph plus a 4-column table (Method, Path, Description, Authorized Role(s)) with all 66 endpoints.
- **§5. Error Code Catalogue** — 2-column table (Error ID, HTTP Status Code) with all 51 errors. Document ends here.

**Coverage audit — all three hard contracts PASS**

- **Contract 1 — Field-Name Coverage: PASS.** Required inventory extracted mechanically from the scaffold: 131 entity field names + 77 POST/PATCH input identifiers + 23 GET query parameters + 13 path parameters = 155 distinct required names. All 155 appear as standalone backticked tokens in the PRD; 0 missing on two independent passes.
- **Contract 2 — Rule Coverage: PASS.** All 15 priority-ordered validations reproduced in order with their error ids and statuses; all 51 error ids explained in §1–§4 prose (not merely listed in §5); all 47 transitions across the 10 state machines narrated, including both independent Policy dimensions (`lifecycle_status` and `limit_status`, the latter travelling in both directions including `EXHAUSTED` back to `PARTIALLY_ERODED`), the self-loops (quote supersede, hour logging, scenario re-model, engagement authorisation), and the two bounded cycles with their termination conditions (`proof_review_round` capped at 2 → claim `DENIED`/`PROOF_INSUFFICIENT`; `verification_round` capped at 2 → `NON_RENEWED`/`CONDITIONS_NOT_MET`). All 9 calculations translated to prose with pinned evaluation and rounding order, including the three dual-variant pairs (attested vs. verified posture basis; indicative vs. bindable premium; `TRAILING_12M` vs. `SAME_PERIOD_PRIOR_YEAR` baseline) with the divergence conditions stated, and the four "wrong way" traps called out explicitly (per-term rounding on engagement amounts; extra-expense cap against the already-rounded BI component; credit cap against the pre-credit premium without iteration; footprint applied once to the summed exposure). Every endpoint side effect, cascade hop, and `version`-increment is accounted for. Three coverage gaps found during the walk and repaired: `ERR_MANDATORY_ATTESTATION_MISSING` on resubmit-controls, `ERR_WAITING_PERIOD_NOT_SATISFIED` re-checked at proof acceptance, and empanelment's candidate-pool effect.
- **Contract 3 — §3 Path Purity: PASS.** §3 spans 230 lines with 1,020 backticked tokens (287 distinct). Zero tokens begin with `/`, zero are bare HTTP methods, zero combine method and path; zero raw `/cyber` occurrences and zero bare method words even outside backticks. Every operation in §3 is named by state-transition framing, role plus action verb, or capability description. Full URL paths appear only in §2.7 and §4.

Additional checks: §2.2 matches the fixed block exactly; §4 has exactly 4 columns and §5 exactly 2 on every row; no pseudocode operators (`==`, `>=`, `+=`, `min(`, `round(`, `AND`, `IN`, …) and no fuzzy quantifiers anywhere in §1–§3.

`SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened, grepped, or referenced.

## Step 5: Generate unit tests — 2026-09-01T18:15:02.422Z

Test generation is complete. Summary for `worklog.md`:

## Test generation — task 2314 (Cyber Insurance Underwriting & Incident Response)

### Files created

**`test_helpers/` (9 files, Stage 1)**
`types.py` (5 roles, 13 vocabulary enums, 12 state enums, TypedDicts for all 14 entities) · `api_client.py` (`ApiClient(GenericApiClient)`, prefix `/cyber`, one method per endpoint — 64 distinct methods exercised by the suite) · `api_errors.py` (all 51 `ErrorId` constants + `ERROR_HTTP_STATUS` registered via `set_error_http_status_map`) · `constants.py` (rating tables, layer factors, control modifiers, catalog rows, attestation profiles, account/tower/vendor specs) · `test_users.py` (per-role headers, two underwriters and two adjusters for the duty splits) · `factories.py` (payload builders) · `fixtures.py` (composite chains: `quoted_application`, `bound_policy`, `confirmed_claim`, `file_proof`, renewal and scenario builders) · `assertions.py` (`assert_money` 2dp, `assert_ratio_4dp`, `assert_score_2dp`, `assert_instant`, `assert_entity_shape`, list helpers) · `__init__.py` barrel.

**`test_suite/` (22 test modules + `conftest.py`, Stage 2) — 165 tests**

Queue A (depth, 10 modules, 40 tests): `test_control_posture_and_premium.py` (6), `test_indemnity_quantification.py` (5), `test_renewal_pricing.py` (3), `test_policy_and_claim_lifecycle.py` (4), `test_scan_and_acceptance_cascades.py` (4), `test_validation_precedence.py` (4), `test_systemic_aggregation.py` (3), `test_cross_entity_state_gates.py` (4), `test_period_and_window_overlap.py` (4), `test_reversal_and_denial_invariants.py` (4).

Queue B (breadth, 12 modules, 125 tests): `test_corner_entities.py` (22), `test_corner_state_machines.py` (15) + `_2.py` (15), `test_corner_validations.py` (7) + `_2.py` (11), `test_corner_calculations.py` (10) + `_2.py` (7), `test_corner_endpoints.py` (10), `test_corner_rbac.py` (11), `test_corner_errors.py` (9), `test_corner_cross_cutting.py` (6), `test_corner_consistency_model.py` (1).

### Instances translated vs skipped
- **Queue A (difficulty): 19/19 instances translated, 0 skipped**, every one covered by ≥2 tests (40 tests over 19 instances).
- **Queue B (corner): 124/124 non-stub instances translated, 0 skipped**, one test each except where an instance needed a paired positive control (125 tests over 124 instances). The 19 stub instances in the index were correctly left alone.
- No instance failed the PRD-first two-condition filter, so there are no gaps to report.

### Design-index adaptations (rule preserved, recipe corrected against the PRD)
- `quote_after_a_new_mandatory_control_is_catalogued_returns_422`: the index added a control keyed `NETWORK_SEGMENTATION`, but the PRD fixes the catalog vocabulary at five keys, so that POST would itself be `ERR_INVALID_REQUEST`. The test seeds four rows and catalogues `INCIDENT_RESPONSE_PLAN` late instead — same `ERR_MANDATORY_CONTROL_GAP` outcome, verified score held at 82.50 so the later score gate cannot mask it.
- Field names that do not exist in the PRD were replaced with the PRD's own: `coinsurance_amount_usd`/`net_amount_usd` → `coinsurance_deduction_usd`/`net_paid_usd`; `extra_expense_allowed_usd` → `extra_expense_component_usd`.
- `unknown_payment_assessment_and_claim_ids`: the renewal-assessment probe uses `Underwriter`, since `ClaimsAdjuster` is not admitted on that read and role authorisation precedes path resolution (403 would mask the asserted 404).
- Two assertions were dropped as not uniquely derivable (null vs `0.00`/`0` for computed fields never yet written on a `DRAFT` application and after a `FAILED` scan); everything else in those instances is asserted in full.
- `panel_selection_tie_broken_by_created_at`: firms are empanelled at three strictly increasing clock instants so the tie-break is unambiguous; `panel_vendor_list_filters_by_type_and_paginates` asserts the offset-1 page as a set, since two firms created at one frozen instant have no PRD-derivable relative order.
- `test_helpers/constants.py` loss-ratio band comments were corrected to the PRD's `0.30 / 0.60 / 1.00` boundaries (they had said 0.40/0.70).

### Audit results
- `python3 -m py_compile` on all 9 helper files and all 23 suite files: **OK**; `__pycache__` removed.
- `pyflakes` on every file: **clean** (no undefined or unused names).
- `pytest --collect-only`: **165 tests collected, 0 collection errors** (no server contacted, no test executed — no implementation was read).
- Every `api.<method>` call in the suite resolves to a real `ApiClient` method (64/64).
- **`Design:` tag audit: 165/165 tests carry exactly one tag as the last non-blank docstring line; all 165 tags resolve against the source yaml; 0 untagged, 0 dual-tagged, 0 dangling.**
- **Citation audit: all 340 quoted spans of ≥20 characters across every module and test docstring are verbatim substrings of `workspace/PRD.md` after whitespace normalisation.** Two defects were found and fixed during the audit: an elided quote using `...` in `test_corner_errors.py`, and a truncated §3.8 sentence in `test_policy_and_claim_lifecycle.py`.
- No `pytest.mark.skip` / `skipif` / `xfail`, no mocking, no `monkeypatch`, no direct DB access anywhere; no file mentions "scaffold"; nothing under `workspace/implementation/` was read or written.

### Reference arithmetic pinned by the suite (hand-verified against the PRD formulas)
Aurora premium 9,000 × 1.00 × 3.4 = 30,600.00 gross → bindable 0.93 = **28,458.00** vs indicative 0.83 = 25,398.00; posture 95.00 attested / 87.50 verified, 82.50 with one mandatory gap. Redstone layer units 1 + 4(0.60) + 5(0.35) = 5.15 → 55,620.00 → **50,058.00**. Bitwise floored to the **7,500.00** minimum. Boundary pair 70.00 quotable at 33,048.00 vs 65.00 refused with `ERR_CONTROL_SCORE_BELOW_MINIMUM`. BI: 60 compensable hours × 5,000.00 × 0.62 → 186,000.00, extra capped at 46,500.00, indemnity **212,500.00**; prior-year override 6,000/hr → **259,000.00** (delta exactly 46,500.00); round-then-sum mode gives **232,500.24**, not 232,500.23. Renewal: 20,000/50,058 = 0.3995 → +0.05 tier → 52,560.90 pre-credit, cap 6,307.31, credit 1,500.00 → **51,060.90**, adjustment 0.0200. Engagement 10 h × 200 + 12,345 × 3.50 = **45,207.50** (terms rounded independently). Systemic: 216 h × 5,000 × 0.60 capped at 500,000 less 250,000 retention net of 20 % coinsurance = 200,000.00 → 0.50 footprint = **100,000.00 (no breach)**, 0.51 = **102,000.00 (breach, policy flagged)**.

## Step 6: Generate implementation — 2026-09-01T18:15:02.422Z

Implementation complete and verified end to end.

## Files created

All under `/home/ubuntu/github/CodingPRD/tasks/task_2314_cyber_insurance_underwriting_incident_response/workspace/implementation/`:

- `start.sh` (executable) — reads `$PORT`, installs Flask only if missing, `exec python3 app.py` in the foreground
- `requirements.txt` — `flask>=3.0`
- `app.py` — app factory, blueprint registration, `ApiError`/`HTTPException`/`Exception` handlers, binds `0.0.0.0:$PORT` (default 10000), `threaded=False`, no reloader
- `db.py` — in-memory `Store` (14 dicts), logical clock (`INITIAL_CLOCK = 2026-08-01T00:00:00Z`), `Decimal` helpers, `new_row`/`touch`/`public`, `_seq` ordering counter
- `response.py` — envelope builders (`meta`/`response_type`/`data`), pagination with 400 on out-of-range `limit`/`offset`
- `validate.py` — typed field extractors (string/enum/number/int/bool/datetime/array/object-array) raising `ERR_INVALID_REQUEST`
- `errors.py` — `ApiError` + 50 error-ID constants
- `middleware.py` — `@endpoint(roles=…)` decorator (401 → 403 → path resolution), entity resolvers, transitive owner resolvers, insured account-scope guards
- `calc.py` — vocabulary, all PRD constants, and the nine calculations
- `cascades.py` — status propagation, waterfall, engagement termination, `limit_status` recompute, claim-denial and policy-cancellation cascades
- `routes/` — `__init__.py`, `common.py`, `catalog.py` (8), `underwriting.py` (21), `policies.py` (8), `claims.py` (11), `proofs.py` (8), `renewal.py` (10)

## Endpoint count

66 registered `@bp.route`s, matching the 66 endpoint rows in PRD §4 exactly.

## Notable design decisions

- **Zero persistence / zero seeding.** Everything lives in module-level dicts; a fresh process starts with all tables empty and the clock at `2026-08-01T00:00:00Z`, so per-test-server isolation is clean.
- **Clock discipline.** All server-generated stamps (`created_at`, `notified_at`, `quote_expires_at`, `modeled_at`, `run_at`, …) come from the logical clock; only `api_request_timestamp` uses wall time. Client-supplied datetimes are echoed verbatim and stored beside `_`-prefixed parsed twins, which `public()` strips from responses.
- **Ordering and versioning.** A monotonic `_seq` per row makes `(created_at, _seq)` a total order despite frequent logical-clock ties; `g.touched_rows` guarantees each row's `version` increments at most once per request.
- **Precedence honoured literally.** The 15-level order is encoded per handler — auth/RBAC before path resolution, scope before SoD, OCC before any state check, control gates before clock gates before coverage-shape before structural before money.
- **Decimal throughout** with `ROUND_HALF_UP` and the PRD's pinned rounding order (components rounded before combination); serialization converts `Decimal` to JSON numbers.
- **Documented ambiguity resolutions:** quote recomputes the posture score live against the current catalog while bind uses the stored gap count; scan completion rewrites `verified_level` as the lower of attested vs observed; engagement `approved_rate_usd` is always pinned from the vendor's pre-approved rate, never the directed rate; `verify-remediation` treats `verification_round < 2` as "return to CONDITIONS_ISSUED" (the PRD's literal gap at round 1); proof filing performs the waiting-period check but defers the covered-section check to acceptance; payment reversal restores sublimit by `gross_amount_usd` and aggregate by `net_paid_usd` and never resurrects terminated engagements.

## Boot and behaviour confirmation

`python3 -m compileall` clean. Booted via `start.sh` on a scratch port and ran a 95-assertion end-to-end script covering catalog → account → application → attestations → submit → scan completion → quote → bind → claim notification → triage → coverage confirmation → panel selection → hour logging → engagement completion → proof of loss → acceptance → payment → reversal → renewal assessment → remediation → renewal quote → systemic model → warranty lapse → cancellation → epoch sweep → pagination, plus 401/403/404/409/412/422 negative paths. **All 95 assertions passed.** Two derived figures were reconciled by hand against PRD §3 (renewal: pre-credit 27,747.32 → credit 750 → `renewal_premium_usd` 26,997.32, `premium_adjustment_pct` -0.0757; systemic: 76 compensable hours → 312,328.77 modelled loss → 62,328.77 after retention → 31,164.39 gross exposure with footprint applied once). Background server killed and `__pycache__` removed; the directory contains only source files.

## Step 7: Run tests and iterate — 2026-09-01T20:01:50.915Z

All 8 parallel rounds are green: **165/165 passed, 0 failed, 0 errors** in every round.

## Summary

**Iterations run:** 2 full 8-round parallel sweeps produced usable signal (plus 3 aborted sweeps — the host was oversubscribed by ~23 concurrent benchmark pipelines, load average peaking at 3062, which killed/erred out earlier attempts; the first sweeps also died because the detached shell was reaped by session cleanup, fixed by running the sweep inside a tmux server).

**Tests deleted:** none. Every failing assertion traced verbatim to PRD prose, so no test hit a STEP 1a silence or STEP 1b non-derivability collapse pattern.

**Fixes applied to `test_suite/`** (both are STEP 2 test-vs-PRD consistency fixes; both make the test *more* faithful to PRD):

- `test_suite/test_control_posture_and_premium.py`, helper `_aurora_submitted_with_pending_scan` — the helper returned the dict from `create_application` (a `DRAFT` row) and `test_scan_finding_lowers_verified_score_below_attested_score` then asserted `attested_control_score == 95.00` / `indicative_premium_usd == 25398.00` on it. PRD §3.4 states the indicative run "fires at submission … and writes `indicative_premium_usd`", so the helper now returns the post-submission application (`application = X.submit_application(...)`). Failed in all 8 rounds before the fix.
- `test_suite/test_corner_state_machines_2.py`, `test_warranty_keys_pinned_at_bind_survive_a_later_catalog_addition` — the test catalogued a 6th control named `NETWORK_SEGMENTATION`, but PRD §3.1 says `control_key` is "drawn from a fixed vocabulary of five security controls: `MFA_PRIVILEGED`, `OFFLINE_BACKUPS`, `EDR_COVERAGE`, `EMAIL_FILTERING`, and `INCIDENT_RESPONSE_PLAN`", so the PRD-faithful implementation correctly returned `ERR_INVALID_REQUEST`. The test now binds against a four-row catalog (`INCIDENT_RESPONSE_PLAN` withheld, with the matching attestation withheld too) and catalogues `INCIDENT_RESPONSE_PLAN` as mandatory *after* the bind — same pinning semantics, legal vocabulary; the count assertion moved 6 → 5 and the negative membership assertion now names the added key. Failed in all 8 rounds before the fix.

**Fixes applied to `workspace/implementation/`:**

- `routes/underwriting.py`, `quote_application` — the quote-time mandatory-gap gate wrote the recomputed `verified_control_score`, `mandatory_gap_count`, and `mandatory_gap_control_keys` onto the application before raising `ERR_MANDATORY_CONTROL_GAP`, so a refused quote mutated the row. PRD §3.5 gate 2 states the recomputation "is stricter than reading the stored `mandatory_gap_count`" and that the gap "blocks the quote even though the stored count still reads 0" — the recomputation is read-only. Those three writes were removed. Fixed `test_corner_errors.py::test_quote_after_a_new_mandatory_control_is_catalogued_is_refused`, which failed in 7 of 8 rounds.

No test was weakened, skipped, or xfailed; no `error_id` assertion was downgraded; no endpoint, field, or capability was added to the implementation; storage remains in-memory dicts with no startup seeding.

## Step 8: Finalize PRD — 2026-09-01T20:06:26.956Z

Done. `PRD_FINALIZED.md` is a one-edit patch of `PRD.md`.

## Line counts
- `PRD.md`: 522 lines → `PRD_FINALIZED.md`: 524 lines (+2, +0.38%). Two prose lines changed/split; no sections added.

## Changes
- **§3.5 (Quoting, gates 2–3 + the on-success paragraph)** — *revise + insert* — pinned that the quote-time verified-basis recomputation is **read-only on refusal** (a refused quote leaves `status`, stored `verified_control_score`, `mandatory_gap_count`, `mandatory_gap_control_keys` and `version` untouched) and that on **success** the recomputed figures are persisted (`verified_control_score` = recomputed score, `mandatory_gap_count` = 0, `mandatory_gap_control_keys` = `[]`) with the bindable premium priced off that same recomputed score; gate 3 now names the recomputed score rather than the stored field. — `implementation/routes/underwriting.py:447-461` (gates at 443-455, persistence at 458-461).

## Per-edit pre-edit search log
**Edit 1 — quote-time recomputation persistence**
- (a) Subject: the verified-basis recomputation performed by `POST /applications/{id}/quote` — which score value the gates consume, and whether the recomputed `verified_control_score` / `mandatory_gap_count` / `mandatory_gap_control_keys` are written to the application.
- (b) Paths enumerated (grepped `verified_control_score|mandatory_gap_count|mandatory_gap_control_keys|control_posture_score` across all `.py`, then read each site): `routes/underwriting.py:96-99` (creation initialises `None/0/[]`); `:196-212` `GET control-posture` (computes both bases live, persists nothing); `:258-261` `resubmit-controls` reads `mandatory_gap_control_keys` as the allowed revision set; `:285-291` `resubmit-controls` resets the three fields to `None/0/[]`; `:409-418` scan-completion hop 3 writes all three on the verified basis and branches to `REMEDIATION_REQUIRED`; `:443-467` `quote_application` (gate order, recomputation, success-only writes, `touch` once); `:536-538` `bind_application` reads the **stored** `mandatory_gap_count`; `cascades.py:34-37` `refresh_attested` (attested basis only, separate field); `cascades.py:17-31` `set_application_status` (not used by the quote path, so no remediation-counter interaction); `calc.py:229-248` `control_posture_score` (never returns `None`; gap list ordered weight DESC then key ASC).
- (c) Wording adjustments made to stay consistent with all of those: scoped the read-only claim to the *quote* gates only (not to the scan cascade at `:409-412` or `resubmit-controls` at `:285-287`, which legitimately do write the same fields); said the success path writes the *recomputed* score rather than redefining §3.4's "the bindable run consumes `verified_control_score`" (both remain true because the write precedes pricing); left §3.5's bind gate ("`mandatory_gap_count` must be zero") untouched since bind reads the stored counter; avoided any general "a refused request mutates nothing" claim, confining the statement to the three quote gates.

## Items deliberately not patched
- **`_aurora_submitted_with_pending_scan` helper fix** — pure fixture bug. PRD §3.2/§3.4 already pin that `indicative_premium_usd` is written at submission and that `attested_control_score` is recomputed on every attestation write; the helper was simply reading the pre-attestation `DRAFT` row. No PRD silence.
- **`NETWORK_SEGMENTATION` catalog fix** — PRD §3.1 already pins the five-key vocabulary and §2.10 step 7 already routes an out-of-domain enum to `ERR_INVALID_REQUEST`; the implementation matches. The rewritten test asserts only membership/count of `warranty_control_keys` (via `sorted(...)`), so it exposes no ordering choice, and I did not add one (impl happens to sort `control_key` ASC, but nothing in the Step 7 item traces to it).

## Step 9: Complete PRD — 2026-09-01T20:20:58.787Z

Done. `PRD_COMPLETED.md` is written and complete.

## Counts

| | |
|---|---|
| Source | `workspace/PRD_FINALIZED.md` — 524 lines, 105,304 chars |
| Output | `workspace/PRD_COMPLETED.md` — 524 lines, 114,536 chars |
| Char delta | **+9,232** |
| Changed passages | 46 hunks / 47 lines (no lines added or removed — every change is an in-paragraph insert or revision; no new sections) |
| Ambiguity-pins | **40** |
| Mismatch-revisions | **6** |

All paths below are relative to `/home/ubuntu/github/CodingPRD/tasks/task_2314_cyber_insurance_underwriting_incident_response/workspace/`.

## Changes

- §2.1 — insert — ambiguity — clock setter takes no headers and never validates `X-User-Role`, so any role value (even one outside the five) is accepted there — `implementation/middleware.py:29`
- §2.2 — insert — ambiguity — `api_request_id` is `req_` plus 20 chars drawn from upper-case letters and digits — `implementation/response.py:14,22`
- §2.2 — revise — **mismatch** — `api_request_timestamp` is read from real wall time, not the logical clock, so it does not move when the clock is set — `implementation/response.py:26,48`
- §2.3 — insert — ambiguity — non-integer or out-of-range `limit`/`offset`, and an out-of-domain filter value, are `ERR_INVALID_REQUEST` — `implementation/response.py:72`, `implementation/routes/common.py:1`
- §2.3 — insert — ambiguity — every ordering (default and declared) breaks `created_at` ties on row insertion order — `implementation/db.py:134`
- §2.3 — insert — ambiguity — an `Insured` supplying a foreign `insured_account_id` filter is refused 403 rather than silently narrowed — `implementation/middleware.py:188`
- §2.4 — insert — ambiguity — a row mutated twice in one request still advances exactly one version — `implementation/db.py:117`
- §2.5 — insert — ambiguity — the clock read echoes the caller's own `current_utc` string verbatim, unrenormalised — `implementation/routes/catalog.py:137`
- §2.5 — insert — ambiguity — the three epoch sweeps run in the stated order; an assessment with no `remediation_due_at` is never swept — `implementation/routes/catalog.py:153,173`
- §2.7 — insert — ambiguity — a missing or non-integer version field is `ERR_INVALID_REQUEST` (400), not a 412 — `implementation/validate.py:116`
- §2.10 — insert — ambiguity — (step 7) absent/empty body reads as `{}`; a non-object body is 400; timestamps accept `Z`, an explicit offset, or no zone (read as UTC) and are stored as spelled; string arrays reject duplicates — `implementation/validate.py:14,153,185`
- §3.2 — insert — ambiguity — an `Insured` naming a foreign account is 403 before the id is resolved, so a foreign nonexistent id is still 403 — `implementation/routes/underwriting.py:74`
- §3.2 — insert — ambiguity — full DRAFT initial field set, including `attested_control_score` at 0.00 (not null) — `implementation/routes/underwriting.py:96,107`
- §3.2 — insert — ambiguity — a catalog-absent `control_key` on attestation is 400, checked before the DRAFT state gate — `implementation/routes/underwriting.py:136`
- §3.3 — insert — ambiguity — scan created with empty `findings`, `critical_finding_count` 0, `completed_at` null — `implementation/routes/underwriting.py:314`
- §3.3 — insert — ambiguity — completion may restate `scan_score`, overwriting the ordered figure; the response body is the scan row — `implementation/routes/underwriting.py:352`
- §3.3 — insert — ambiguity — findings on a FAILED scan are still schema-validated (unknown/duplicate key = 400) and then ignored — `implementation/routes/underwriting.py:361`
- §3.3 — insert — ambiguity — resubmit `attestations` must be non-empty, out-of-gap key is 400 after the state gate, missing attestation rows are created — `implementation/routes/underwriting.py:245`
- §3.3 — insert — ambiguity — resubmission clears `premium_usd` to null, since every arrival in SUBMITTED does — `implementation/cascades.py:29`
- §3.4 — insert — ambiguity — an empty catalog yields score 0.00 with an empty gap list, no division, no error — `implementation/calc.py:229`
- §3.4 — insert — ambiguity — on the posture read `verified_score` is null until a completed scan exists, gaps are always verified-basis, and `quotable` is the four-way conjunction — `implementation/routes/underwriting.py:197`
- §3.5 — insert — ambiguity — an application carrying no scan at all fails the latest-scan gate identically — `implementation/routes/underwriting.py:445`
- §3.5 — insert — ambiguity — `declined_reason` required and non-empty — `implementation/routes/underwriting.py:476`
- §3.5 — revise — **mismatch** — bind gates run gap-first then expiry (`ERR_MANDATORY_CONTROL_GAP` before `ERR_QUOTE_EXPIRED`) — `implementation/routes/underwriting.py:537,541`
- §3.5 — insert — ambiguity — policy period bounds stored as the caller spelled them; sections created in request order; `warranty_control_keys` sorted ascending — `implementation/routes/underwriting.py:586,594`
- §3.6 — insert — ambiguity — `lapsed_control_keys` required but may be empty, drawn from the five keys, need not subset `warranty_control_keys`, and no policy state gates the report — `implementation/routes/policies.py:89`
- §3.6 — insert — ambiguity — `NONE` remains an accepted `dependency_key`, failing the named-dependency check under `NAMED_ONLY` — `implementation/routes/claims.py:29,62`
- §3.6 — insert — ambiguity — claim opens with `covered_section_keys` empty, `reservation_of_rights` false, `denial_reason` null — `implementation/routes/claims.py:95`
- §3.6 — revise — **mismatch** — confirm-coverage runs the tower-membership check first, ahead of remaining schema checks and the claim state gate, reporting 404 even for a non-vocabulary string; `initial_reserve_usd` required and non-negative — `implementation/routes/claims.py:160,171`
- §3.6 — insert — ambiguity — `denial_reason` and `cancellation_reason` both required and non-empty — `implementation/routes/claims.py:202`, `implementation/routes/policies.py:1`
- §3.7 — insert — ambiguity — the aggregate gate is the last check the authorisation makes, after the firm is chosen, and both conditions raise `ERR_AGGREGATE_LIMIT_EXHAUSTED` — `implementation/routes/claims.py:262`
- §3.7 — revise — **mismatch** — direction bypasses the selector's `vendor_type` and `specialty_sectors` filters entirely — `implementation/routes/claims.py:239`
- §3.7 — revise — **mismatch** — `directed_rate_usd` is validated then discarded, never persisted; ignored without a `panel_vendor_id` — `implementation/routes/claims.py:256`
- §3.7 — insert — ambiguity — `hours` merely non-negative (zero accepted, still advances the engagement); `records_notified` optional non-negative integer defaulting to 0 — `implementation/routes/claims.py:318`
- §3.7 — insert — ambiguity — the eligible-section check precedes all mutation and the limit check; a 0.00 incurred amount still runs the waterfall and writes no payment row — `implementation/routes/claims.py:340,356,365`
- §3.8 — insert — ambiguity — `ERR_WAITING_PERIOD_NOT_SATISFIED` also covers BEC/DATA_THEFT and missing-tower-section claims, which can therefore never file; the `covered_section_keys` restriction applies only at acceptance — `implementation/routes/proofs.py:31,78`
- §3.8 — insert — ambiguity — request-info returns the proof row on both branches — `implementation/routes/proofs.py:154,164`
- §3.8 — insert — ambiguity — the denial branch leaves `proof_review_round` standing at 2 — `implementation/routes/proofs.py:147`
- §3.8 — insert — ambiguity — a mapped key outside `covered_section_keys` raises `ERR_NO_ELIGIBLE_COVERAGE_SECTION` before the exhausted-aggregate check — `implementation/routes/proofs.py:194,196,199`
- §3.8 — insert — ambiguity — an allocation moving no aggregate capacity leaves the policy's `version` and `limit_status` untouched while the claim's still advances — `implementation/cascades.py:137,144`
- §3.8 — insert — ambiguity — `reversal_reason` required non-empty and stored (null until reversal); `retention_absorbed_usd` floored at 0.00; the case reserve is not reinstated — `implementation/routes/proofs.py:257,268,282`
- §3.9 — revise — **mismatch** — the INFORCE policy gate is checked before the renewal-window gate — `implementation/routes/renewal.py:34,38`
- §3.9 — insert — ambiguity — `required_control_keys` required but may be empty, drawn from the fixed five-key vocabulary rather than the live catalog, stored sorted; `remediation_due_at` stored as spelled — `implementation/routes/renewal.py:30,45`
- §3.9 — insert — ambiguity — assessment opens with both key lists empty and `loss_ratio`, `premium_adjustment_pct`, `renewal_premium_usd`, `non_renewal_reason` all null — `implementation/routes/renewal.py:46`
- §3.9 — insert — ambiguity — `submitted_control_keys` may be empty; a non-required key is `ERR_INVALID_REQUEST` after the state gate; stored sorted — `implementation/routes/renewal.py:86,92,95`
- §3.9 — insert — ambiguity — `verified_control_keys` may be empty and need not subset required or submitted keys, yet still earns control credit — `implementation/routes/renewal.py:106,113`
- §3.9 — insert — ambiguity — scenario opens with `modeled_gross_exposure_usd` and `modeled_at` null and `qualifying_definitions` in supplied order; the model run has no state gate — `implementation/routes/renewal.py:180,186,211`
- §5 — insert — ambiguity — an unroutable path/method returns the standard envelope with `ERR_INVALID_REQUEST` on 404/405 rather than 400; trailing slashes are insignificant — `implementation/app.py:26,39`

Read prohibitions were honored: no `SCAFFOLD*.yaml` and no `worklog.md` were opened. `test_suite/` and `test_helpers/` were used only as auxiliary cross-reference, never as authority.
