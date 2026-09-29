# Worklog — task_2404_children_s_online_privacy_compliance

## Step 1: Create task directory — 2026-09-02T07:45:00.000Z

Created `tasks/task_2404_children_s_online_privacy_compliance/` and `tasks/task_2404_children_s_online_privacy_compliance/workspace/` (pre-allocated name used verbatim; no index scan performed).

## Step 2: Generate scaffold — 2026-09-02T09:31:00.000Z

Scaffold 2404 is complete and lint-clean.

## Files

- `/home/ubuntu/github/CodingPRD/tasks/task_2404_children_s_online_privacy_compliance/SCAFFOLD.yaml` (1707 lines) — §1.0–§1.7 only, no design keys
- `/home/ubuntu/github/CodingPRD/tasks/task_2404_children_s_online_privacy_compliance/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (2231 lines) — single key `scaffold_difficulty_design`
- `/home/ubuntu/github/CodingPRD/tasks/task_2404_children_s_online_privacy_compliance/SCAFFOLD_CORNER_DESIGN.yaml` (3545 lines) — single key `scaffold_corner_design`

## SCAFFOLD.yaml contents

12 entities · 8 state machines · 2 OCC concurrency rules · 11 calculations · 28 ordered validations (priorities 10→130) · 39 endpoints · 58 error codes · 5 roles (all with `identity:`; `Parent` is `entity_backed:ConsentRequest`, the rest opaque).

Profile: primary `compliance_audit`, secondary `access_control_matrix`; layers `optimistic_concurrency`, `cascading_side_effects`, `dual_variant_calculation`, `rate_threshold_triggers`; flat topology; parallel state-machine shape (the service carries an independent determination axis and posture axis); `segregation_of_duties` role model; immediate consistency.

## Design instances

- §1.8: **22 instances** across all nine required `rule_id`s — `dual_variant_calc` 2, `combinatorial_formula` 2, `non_linear_state_machine` 3, `transitive_cascade` 2, `priority_pair_validation_conflict` 3, `boundary_precision_check` 3, `cross_entity_state_dependency` 3, `resource_temporal_overlap` 2, `compensating_invariant` 2.
- §1.9: **65 instances** (47 with full `test_recipe`, 18 `excluded_because:` stubs) across all nine sections — entities 12, state_machines 13, calculations 10, validations 13, endpoints 4, errors 4, rbac 3, cross_cutting_complexity_layers 5, consistency_model 1. Every stub cites an existing §1.8 instance by name; no stub carries a recipe.
- 1017 total API calls; all 58 error codes are asserted somewhere in the two design files.

## Notable design decisions (harder-than-expert levers)

- **Dual-variant determination**: `AUDIENCE_FIRST` vs `DESIGN_FIRST` variant selection with different threshold ladders (share 0.4000/0.2000 vs design 0.75/0.65/0.45), on top of a **normalized weighted design score** that divides by *present* factor points only and rounds each contribution to 2 dp *before* summation — so rounding order flips two determination bands.
- **Pinned-vs-live snapshot**: `required_tier_at_creation` is pinned from the service's approved persistent-identifier integration set at consent creation, so a later integration approval cannot retroactively invalidate — but a stale OCC token can.
- **Six-link deletion cascade** from rights-request fulfilment → record disposal → consent revocation → disclosure-consent count hitting 0 → integration re-audit → exposure/posture recompute, ending in a posture *downgrade* from FROZEN to RESTRICTED.
- **Strict 6-clause posture ladder** (override → exposure ≥80 FROZEN → open audits → exposure ≥40 → safe-harbor LAPSED → OPEN) with integer exposure points doubled for persistent identifiers, giving exact-40 and exact-80 boundary cases and a 0-point CDN case.
- **Two-run secure disposal** with inclusive due-date boundary, plus `live_child_data_element_count` returning to 0 while `lifetime_collected_element_count` only grows (compensating invariant), mirrored by exposure points reversing on BLOCK while `audit_decision_count` never does.
- **Neutrality codes** for age screening emitted in fixed order, with `UNVERIFIED_INHERIT` gated on `mechanism == ACCOUNT_AGE_INHERIT AND inherited_from_verified_account == false`.
- **Distinct 403s**: endpoint-level `ERR_ROLE_NOT_PERMITTED` (p20) vs transition-actor `ERR_TRANSITION_ROLE_NOT_PERMITTED` (p72) vs Parent identity binding `ERR_NOT_CONSENT_HOLDER` (p30), with priority ordering asserted (role gate decides before the identity lookup).
- **OCC on `OnlineService.version` only**, guarding notice and consent creation; every OCC call is preceded by a fresh `GET` capture, and the refused attempt is proven not to advance the version.
- Logical clock default pinned to exactly `2026-08-01T00:00:00Z` and asserted by a corner instance that makes no clock call before its first write.

## Lint verdict (verbatim)

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2404_children_s_online_privacy_compliance/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2404_children_s_online_privacy_compliance/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2404_children_s_online_privacy_compliance/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    39
  §1.1 entities declared:     12
  §1.8 instances scanned:     22
  §1.9 instances scanned:     47
  Calls scanned (§1.8+§1.9):  1017

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Fixes applied during verification: a bracketed JSONPath capture broke YAML flow parsing (now quoted, 10 sites); one `GET /parental-notices/{id}` call was not a declared endpoint (recomposed as the service sub-resource lookup); one payload carried a non-input field; three difficulty-file asserts used the forbidden word "simultaneously" (reworded to "also-violated"). Also verified: unique names across both design files, full placeholder closure (no `${var}` used before capture), no literal OCC tokens, and every stub's cited difficulty instance exists.

## Step 3: Copy shared files — 2026-09-02T09:31:30.000Z

Copied `INSTRUCTION.md` to `tasks/task_2404_children_s_online_privacy_compliance/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-02T09:49:00.000Z

PRD written to `/home/ubuntu/github/CodingPRD/tasks/task_2404_children_s_online_privacy_compliance/workspace/PRD.md`.

**Line count:** 466 lines (~11,950 words)

**Sections:** `# Children's Online Privacy Compliance API — Product Requirements Document`
- §1 Introduction (3 paragraphs)
- §2 Global Specifications & System-Wide Principles — 2.1 User and Role-Based Access Control · 2.2 API Response Structure (pasted verbatim, byte-identical to `section-2.2-response-structure.md`) · 2.3 Pagination · 2.4 Resource Identity, Timestamps and the Logical Clock · 2.5 The Two Compliance Axes of an Online Service · 2.6 Version Stamping, Cascade Settlement and Optimistic Concurrency · 2.7 Numeric Precision, Rounding and Ordering Keys · 2.8 Reverse-Lookup Reads, Filtering and Identifier Resolution · 2.9 Validation Precedence · 2.10 Bounded Loops and Second-Pair-of-Eyes Rules
- §3 Business Logic & Workflows — 10 domain-grouped subsections (service registration + evidence; determination + posture; neutral age screening; parental notice; verifiable consent; activities/minimization/collection; third-party integrations + audits; parental rights + deletion cascade; retention/compliance runs/disposal; safe harbor + annual assessment)
- §4 Endpoint Definitions — 4-column table, all 39 endpoints, preceded by the 201-for-create / 200-for-modify paragraph
- §5 Error Code Catalogue — 2-column table, all 58 error IDs with matching HTTP statuses. Document ends here; no audit footer.

**Coverage audits (three passes run programmatically against `SCAFFOLD.yaml`):**

```
Field coverage check:
- entities[].fields: 128 required, 128 present, 0 missing
- endpoints[].request_body / input identifiers: 75 required, 75 present, 0 missing
- endpoints[].query_params: folded into endpoints[].input in this scaffold — included in the 75, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 28 checked, 28 expressed in prose (§2.9 renders the full 10→130 precedence chain), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected_service_version + ERR_STALE_SERVICE_VERSION all named), 0 missing
- state_machines[].transitions: 36 checked, 36 fully expressed, 0 missing
- calculations[]: 11 checked, 11 fully expressed, 0 missing
- validations[] conditions: 58 checked, 58 matchable to error_id in prose before §5, 0 missing
- endpoints[].side_effects / applies_to: 20 side-effect blocks + 28 applies_to scopings checked, all expressed, 0 missing
- entities[].fields[] structured content: 47 checked, 47 reconstructible from prose, 0 missing
- sibling-branch symmetry: 12 groups checked, 12 with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 918
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

The purity scanner surfaces two `DELETE` tokens in §3.8; both are the `right_type` enum value, not HTTP methods, and both now sit in unambiguous enum context (`a `right_type` of `REVIEW`, `DELETE` or `REFUSE_FURTHER_COLLECTION``, and `For a `right_type` of `DELETE``). Not a true violation.

**Zero-Silence notes:**
- Only one genuine scaffold ambiguity: validation priority 55 (`ERR_SERVICE_SCOPE_MISMATCH`) lists `POST /consent-requests` in its `applies_to`, but its declared check names only a referenced `ConsentRequest` and `ActivityDefinition` — neither is a body FK on consent creation (whose FKs are `service_id` and `notice_id`). I rendered the check text and the full three-endpoint scope verbatim rather than inventing a notice-scoping rule, so the check is vacuous on that one endpoint exactly as specified.
- Deliberate emphasis added where silence would be costly: the two-run disposal invariant, the pinned rounding order for `design_score`, the frozen `required_tier_at_creation` and the reciprocal audit-set exclusion that breaks its circularity, the normative clause order on certification (`ERR_OPEN_FINDINGS_PRESENT` before `ERR_SEGREGATION_OF_DUTIES`), the `ERR_CONSENT_REVOKED`-beats-`ERR_DIRECT_NOTICE_NOT_DELIVERED` precedence, half-open sample windows vs. closed retention ranges with a one-day handover, strict `<` on both safe-harbor clock comparisons, and the escalation cascade firing only from an already-assessed status.
- The two withheld files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened, grepped or referenced; no sibling task directory was read. All audit scripts were scoped to `SCAFFOLD.yaml` and the generated PRD only.

## Step 5: Generate unit tests — 2026-09-02T11:35:00.000Z

Queue B is now complete; the whole suite is generated, audited and green on static checks.

## Files created

**Stage 1 — `test_helpers/`** (9 files)
`__init__.py`, `api_client.py`, `api_errors.py`, `assertions.py`, `constants.py`, `factories.py`, `fixtures.py`, `test_users.py`, `types.py`

**Stage 2 — `.../test_suite/`** (`conftest.py` + 17 test modules, 120 tests)

| file | tests | source |
|---|---|---|
| `test_01_child_directed_determination.py` | 14 | queue A |
| `test_02_compliance_posture_and_exposure.py` | 13 | queue A |
| `test_03_age_screen_revision_cycle.py` | 5 | queue A |
| `test_04_verifiable_consent_and_notice_delivery.py` | 10 | queue A |
| `test_05_child_data_collection_gates.py` | 6 | queue A |
| `test_06_parental_rights_scope_and_deletion.py` | 6 | queue A |
| `test_07_retention_schedules_and_disposal.py` | 10 | queue A |
| `test_08_safe_harbor_certification.py` | 6 | queue A |
| `test_09_entity_representations.py` | 12 | Corner/entities |
| `test_10_lifecycle_state_machines.py` | 9 | Corner/state_machines |
| `test_11_computed_values_and_orders.py` | 7 | Corner/calculations |
| `test_12_validation_precedence.py` | 9 | Corner/validations |
| `test_13_endpoint_contracts.py` | 3 | Corner/endpoints |
| `test_14_error_semantics.py` | 4 | Corner/errors |
| `test_15_role_permissions.py` | 3 | Corner/rbac |
| `test_16_service_version_guard.py` | 2 | Corner/cross_cutting_complexity_layers |
| `test_17_immediate_consistency.py` | 1 | Corner/consistency_model |

## Counts per queue

- **Queue A (Difficulty, §1.8):** 70 tests covering **22/22** non-stub instances.
- **Queue B (Corner, §1.9):** 50 tests covering **47/47** non-stub instances.
- **Total:** 120 tests, 120 `Design:` lines, 69 distinct instances — full budget, no double-counting.

## Instances skipped

**None.** Every non-stub instance in both indices passed the PRD-first two-condition filter and was translated. The 18 `excluded_because` corner stubs (4 state_machines, 5 calculations, 5 validations, 1 endpoints, 3 cross_cutting) were deliberately not translated, as required.

## Audits run

- **Design-tag audit (scripted):** every test docstring ends with exactly one `Design:` line; every tag resolves to a real, non-stub instance name in the source yaml; no dual tags, no untagged tests, no tags pointing at stubs.
- **Citation audit (scripted, 253 quoted fragments):** every quoted fragment is now a literal whitespace-normalised substring of `workspace/PRD.md`, and every test carries at least one >=8-word verbatim quotation. Four repairs were needed: three quotes had a sentence-final period pulled inside the quotation marks (`ERR_CONSENT_NOT_GRANTED`, `ERR_AGE_SCREEN_NOT_ACTIVE`, `third_party_exposure_points`), one used a bracketed alteration `"accept[s] `status`"` (replaced with the verbatim clause), and four thin citations were widened to full PRD sentences.
- **Vocabulary audit:** the word "scaffold" no longer appears anywhere in `test_suite/` or `test_helpers/` (a local helper `_collection_scaffold` in `test_05` was renamed to `_collection_surroundings`).
- **Static checks:** `pyflakes` clean (exit 0) across all of `test_suite/`; `py_compile` clean; `pytest --collect-only` collects exactly **120 tests** with no import or collection errors. Note that `pyflakes test_helpers/*.py` exits 1 purely from `__init__.py` star-import re-export noise — that is expected, not a defect.

Nothing was executed against a live server, and neither `workspace/implementation/` nor any sibling task directory was read.

## Step 6: Generate implementation — 2026-09-02T11:12:00.000Z

Implementation complete and verified.

## Files created
All under `workspace/implementation/`:

- `start.sh` (guarded `pip install`, then `exec python3 app.py`), `requirements.txt` (`Flask==3.0.3`)
- `app.py` — blueprint registration + `ApiError`/404/405/400/500 handlers, `app.run(host="0.0.0.0", port=$PORT|10000)`
- `constants.py`, `errors.py` (all 60 error ids -> HTTP), `timeutil.py`, `db.py`, `response.py`, `middleware.py`, `calculations.py`, `serializers.py`, `helpers.py`
- `routes/` (13 modules): `online_services`, `evidence`, `age_screens`, `notices`, `activities`, `consents`, `records`, `rights`, `integrations`, `retention`, `compliance_runs`, `safe_harbor`, `clock`

## Endpoint count
**39 routes**, matching the PRD §4 table one-for-one (I verified the table is 39 rows, not 40).

## Notable design decisions
- **Every computed field is derived at read time** (posture, safe_harbor_status, all nine counters, exposure points, `disclosed_in_notice`, `missing_content_keys`, `neutrality_violation_codes`, `design_score`, `audience_child_share`). This makes the transitive cascades automatically consistent; only genuine state changes (integration -> `AUDIT_PENDING`, consent revoke/supersede, notice supersede, screen retire, record dispose) are applied explicitly.
- **§2.9 wins over §3.x prose** where they disagree: integration approval is posture (11) -> behavioral gate (14) -> disclosure (18), not §3.7's narrative order; retention is overlap (16) -> invalid-period/disposal-method (21); collection is consent-status (9) -> posture (11) -> determination/age-screen (12) -> notice (13) -> minimization (20) -> schedule (25); consent grant is tier/EMAIL_PLUS (13) -> window (17).
- Logical clock only (`db.current_utc`, startup `2026-08-01T00:00:00Z`); wall clock used solely for `meta.api_request_timestamp`.
- `Decimal` + `ROUND_HALF_UP`; design_score rounds per-factor contributions **before** summation; share is one ratio over summed numerator/denominator at 4dp.
- OCC (`expected_service_version`) on exactly `POST /parental-notices` and `POST /consent-requests`; missing/non-int -> 422, mismatch -> 412.
- Parent ownership evaluated before FK/path resolution on rights-request creation; for path-addressed reads a 403 is returned when the row exists but isn't the parent's, 404 when it doesn't exist.
- Storage is in-memory dicts only — no sqlite, no file I/O, no `/tmp`, no seeding (grep confirms no `open(`, `sqlite3`, `pickle`, `json.dump`).
- `activity_code` uniqueness is intentionally not enforced: the error catalogue has no code for it.

## Boot / behaviour confirmation
Booted via `bash start.sh` twice (fresh process each time): starts in ~1s, `GET /online-services` returns `total_count: 0` and the clock reads `2026-08-01T00:00:00.000Z` on every boot. A 77-assertion smoke run exercised the whole domain end-to-end and passed (the single "failure" was a wrong expectation in my own test script — the adjacency rule was then verified separately: same-day adjacency 409, sub-day gap 409, exactly-one-day gap 201). Verified live: determination variants (`DESIGN_FIRST` 1.00 -> `CHILD_DIRECTED_PRIMARY`; `AUDIENCE_FIRST` share 0.4000 -> primary), `ERR_INSUFFICIENT_EVIDENCE`, evidence field-group mismatch and sample overlap, notice completeness/publish/supersede, OCC 412, consent lifecycle incl. tier-bump (required tier 2 vs EMAIL_PLUS tier 1 -> 422) and `ERR_POSTURE_FROZEN`, collection gates, two-run secure disposal (`scheduled_count 1 / disposed_count 0` then `disposed_count 1`), exposure 80 -> `FROZEN`, `ERR_OPEN_AUDITS_PRESENT`, the determination-escalation cascade (`audit_note` = "re-audit forced by child-directed determination"), the revocation -> disclosure-loss cascade, screen neutrality/role/loop bounds, rights verification tier + attempt bounds + fulfilment, and safe-harbor findings -> regulator -> segregation ordering with `expires_at` = certified_at + 365d.

## Step 7: Run tests and iterate — 2026-09-02T13:25:00.000Z

Resume note (orchestrator): this task was resumed with Steps 1–6 already satisfied on disk
(SCAFFOLD trio non-empty, workspace/INSTRUCTION.md, complete workspace/PRD.md at 465 lines
ending in the full error-code table, test_suite/ with 17 test_*.py + test_helpers/,
workspace/implementation/ with start.sh + 14 route modules). Per the resume protocol none of
those steps were re-run. A previous attempt had started Step 7 and died mid-sweep: the stale
round.5.log ended in `ServerStartTimeout: Server did not respond ... within 120.0s` while the
port registry showed 180+ concurrent holders, i.e. pure host CPU contention, not an artifact
defect. An orchestrator-side boot probe confirmed the server binds and serves in ~12s on a
quiet host. Stale results.*.json and round.*.log were deleted before the first sweep, and the
sweep timeouts were raised to `--timeout 300 --test-timeout 60` to absorb the contention.

All 8 parallel rounds report 120/120. Clean sweep achieved.

**Iterations run:** 2 (baseline sweep + one fix round; both sweeps 8 concurrent rounds, `per-test-server` isolation, 120 tests/round)

**Baseline:** 118/120 in all 8 rounds — two failures, both deterministic (8/8 rounds, no load flakiness anywhere in the suite; no `ServerStartTimeout` / `RemoteDisconnected` observed).

**Final:** 120/120 in all 8 rounds.

**Tests deleted:** none. Both failures traced to test bugs that were fixable toward greater PRD fidelity, not to PRD silence.

**Fixes applied to `test_helpers/`:** none — no shared fixture was at fault.

**Fixes applied to `test_suite/`:**
- `test_suite/test_05_child_data_collection_gates.py` — local fixture `_collection_surroundings`: the `DRAFT → IN_REVIEW` transition's response was discarded (`set_screen_status(...)` called without assignment), so on the `activate_screen=False` path the returned dict carried the stale creation-time screen. `test_04_a_screen_still_in_review_does_not_permit_collection` then asserted `screen["status"] == "IN_REVIEW"` against a `DRAFT` snapshot. Now `screen = set_screen_status(...)`. The transition itself was always performed correctly server-side (the sibling `test_05` proves it), so this was purely a stale local copy.
- `test_suite/test_12_validation_precedence.py` — `test_07_submitted_and_verifying_both_report_the_dedicated_code`: the final assertion (re-fulfilling an already-`FULFILLED` request) expected `ERR_INVALID_STATE`, inferred from "`REJECTED` and `FULFILLED` are both terminal." That contradicts PRD §3.8's verbatim universal: *"Attempting fulfilment from any status other than `VERIFIED` is refused with `ERR_RIGHTS_REQUEST_NOT_VERIFIED` (HTTP 409)."* `FULFILLED` is a status other than `VERIFIED`, and §2.9 step 9 reserves `ERR_INVALID_STATE` for "where no more specific code applies" — a more specific code does apply here. Assertion corrected to `ERR_RIGHTS_REQUEST_NOT_VERIFIED` / 409 (still an exact `error_id` assertion — no downgrade to a status-only check), plus a one-line docstring wording fix. The test already quoted the governing sentence in its own docstring.

**Fixes applied to `implementation/`:** none. The implementation was PRD-faithful on both counts; `routes/rights.py:140-141` already encodes the §3.8 rule exactly (`if to_status == "FULFILLED" and current != "VERIFIED": fail("ERR_RIGHTS_REQUEST_NOT_VERIFIED")`), and no PRD-required check was weakened or removed.

## Step 8: Finalize PRD — 2026-09-02T13:32:00.000Z

Orchestrator note: Step 8's skip condition was NOT met (Step 7 applied 2 `test_suite/` fixes),
so the finalizer ran. It concluded both fixes were pure test bugs against already-explicit PRD
prose, so the output is byte-identical to PRD.md by design — no edits were manufactured.

`workspace/PRD_FINALIZED.md` is created and is **byte-identical to PRD.md**. Neither Step 7 item revealed a PRD silence or a PRD/impl mismatch, so there is nothing to pin. No edits were invented.

## Line counts
- PRD.md: 465 lines
- PRD_FINALIZED.md: 465 lines
- %-delta: 0.00% (md5 `b0a867e17c145cc90cc3a44f6bff5fb0` for both)

## Changes
None. One bullet per change is therefore empty.

## Per-item analysis (why each Step 7 item produced no edit)

**Item 1 — `test_suite/test_05_child_data_collection_gates.py`, `_collection_surroundings` stale local screen.**
- (a) Subject: the response body of `POST /age-screens/{id}/status` for the `DRAFT → IN_REVIEW` transition — specifically whether the server returns the *updated* screen representation.
- (b) Impl paths enumerated and read: `implementation/routes/age_screens.py` — the whole `set_age_screen_status` handler (`TRANSITION_ACTOR` table lines 22-28, legality/role gates 68-71, per-transition preconditions 73-78, mutation 80-98, `touch(screen)` + `return ok(age_screen_out(screen))` at 99-100); plus the sibling `create_age_screen` (lines 31-45) for the birth-state contract, and `serializers.py:age_screen_out` / `calculations.py:age_screen_neutrality` for the derived `neutrality_violation_codes`. Cross-checked the test's own sibling `test_05_activating_the_screen_opens_collection`, which reads the same endpoint's return value and passed at baseline — proving the server-side transition and its response were always correct.
- Verdict: PRD already determines this in two places, verbatim — §2.2 ("operations that create or modify a resource will return the created or updated resource object in the `data` field") and §3.3 ("Submitting it for review moves it `DRAFT → IN_REVIEW`"). The impl matches both. The failure was entirely a discarded return value in a test-local fixture (`set_screen_status(...)` called without assignment), leaving a creation-time `DRAFT` snapshot in the dict the test then asserted against. Pure fixture bug; no PRD-open choice was pinned by the implementation.
- (c) Wording adjustment: n/a (no edit committed).

**Item 2 — `test_suite/test_12_validation_precedence.py::test_07`, re-fulfilling an already-`FULFILLED` request.**
- (a) Subject: which error a fulfilment attempt yields when the current status is not `VERIFIED`, and in particular whether the terminal statuses `REJECTED`/`FULFILLED` route to `ERR_INVALID_STATE` or to the dedicated `ERR_RIGHTS_REQUEST_NOT_VERIFIED`.
- (b) Impl paths enumerated and read: `implementation/routes/rights.py` — `set_rights_status` in full, notably the conditional body-field step (`req_enum(data, "scope_mode", SCOPE_MODES)` at lines ~127-131), the dedicated guard at lines 140-141 (`if to_status == "FULFILLED" and current != "VERIFIED": fail("ERR_RIGHTS_REQUEST_NOT_VERIFIED")`) placed *ahead* of the generic `if transition not in TRANSITION_ACTOR: fail("ERR_INVALID_STATE")`, the `TRANSITION_ACTOR` table (lines 35-42, which contains no outbound edge from `FULFILLED` or `REJECTED`, so both are terminal), the per-transition role gate, and the `VERIFIED → FULFILLED` body (scope resolution via `calc.resolve_rights_scope`, `fulfilled_at`, the `REFUSE_FURTHER_COLLECTION`/`DELETE` cascades and `revoke_consent(consent, "DELETION_FULFILLED")` + `disclosure_loss_cascade`). Also read PRD §3.8 line 318 and §2.9 step 9 (line 163).
- Verdict: PRD §3.8 already states the universal verbatim — "Attempting fulfilment from any status other than `VERIFIED` is refused with `ERR_RIGHTS_REQUEST_NOT_VERIFIED` (HTTP 409)" — and §2.9 step 9 explicitly reserves `ERR_INVALID_STATE` for "where no more specific code applies". `FULFILLED` is a status other than `VERIFIED`, and a more specific code does apply. The impl encodes exactly this, in exactly this precedence. The test had misinferred `ERR_INVALID_STATE` from the unrelated "`REJECTED` and `FULFILLED` are both terminal" sentence while quoting the governing sentence in its own docstring. Test-side misinference contradicted by already-explicit PRD prose; no silence, no mismatch.
- (c) Wording adjustment: n/a (no edit committed).

## Notes
- Step 7 applied zero implementation fixes and zero test deletions, consistent with this outcome.
- Two unrelated candidate ambiguities were observed while enumerating (impl applies a supplied `review_note` on any age-screen transition, not only `IN_REVIEW → REJECTED`; and the §2.9 step-8-before-step-9 ordering that makes a `scope_mode`-less fulfilment from `SUBMITTED` report `ERR_INVALID_REQUEST` 422 rather than the 409). Neither traces to a `<step_7_diff>` item — the relevant assertions passed at baseline and were never touched — so both were left alone per the hard scope rule. Both are in scope for Step 9's global scan.

## Step 9: Complete PRD — 2026-09-02T13:50:00.000Z

Orchestrator note: Step 9 was given the two out-of-scope ambiguity candidates Step 8 had spotted
but could not act on (§3.3 `review_note` breadth, §3.8 step-8/step-9 ordering), flagged explicitly
as hints to verify rather than a work list. Both were independently confirmed against the
implementation and pinned. Verified post-hoc that `implementation/` mtimes are unchanged since
Step 6 (10:0x) — Step 9 was read-only against the alignment target, as required — and that the
live probe server it used was stopped.

Deliverable written: `workspace/PRD_COMPLETED.md`.

**Size**
- Source `workspace/PRD_FINALIZED.md` (byte-identical to `PRD.md`): 465 lines, 91,015 bytes (90,744 chars)
- `workspace/PRD_COMPLETED.md`: 466 lines, 102,076 bytes (101,739 chars)
- Delta: +1 line, +10,995 chars; 25 changed line-blocks, no new sections, no new headings, no deletions of existing requirements

**Counts**: 36 individual pins — 29 ambiguity-pins, 7 mismatch-revisions.

**Changes**
- §2.1 — revise — ambiguity — an identity header present but empty counts as absent → 401 `ERR_UNAUTHENTICATED` — middleware.py:26
- §2.2 (success format) — revise — ambiguity — `api_request_timestamp` comes from wall clock, not the §2.4 logical clock — response.py:28
- §2.2 (error format) — insert — ambiguity — absent/empty body behaves as `{}`; unparseable or non-object body → `ERR_INVALID_REQUEST` 422 — middleware.py:38, app.py:75
- §2.3 — insert — ambiguity — empty-string `limit`/`offset` = omitted; non-integer or out-of-bounds → 422 — response.py:67
- §2.3 — insert — ambiguity — ties in the ordering key break on insertion order (stable list order) — db.py:53
- §2.3 — revise — ambiguity — `total_count` is the filtered size before windowing; `has_more` = `offset + len(items) < total_count` — response.py:46
- §2.4 — insert — ambiguity — `created_at`/`updated_at` are stamped from the logical clock, not wall time — db.py:37
- §2.6 — insert — **mismatch** — the blanket "accepted request bumps `OnlineService.version`" is false; the nine non-bumping write categories enumerated inline — helpers.py:69
- §2.6 — insert — ambiguity — `expected_service_version` absent/null/non-integer → 422 before any 412 comparison — helpers.py:63
- §2.7 — insert — ambiguity — `design_score`/`audience_child_share` are JSON numbers, so `0.00` renders `0.0` — serializers.py:6
- §2.8 — insert — ambiguity — missing/null/empty/non-string body FK → 422, not 404 — helpers.py:55
- §2.8 — revise — **mismatch** — `POST /consent-requests` coherence guard checks `notice_id`; per-endpoint coherence keys named correctly — consents.py:46
- §2.8 — insert — ambiguity — filters are exact-equality, illegal enum/year values yield an empty page (not an error), empty string = unsupplied, unknown params ignored — helpers.py:124
- §2.9 — insert — ambiguity — ownership 403 precedes existence when decidable from the supplied identifier (incl. an omitted `consent_request_id`); 404 wins when the stored row is needed — rights.py:59, rights.py:48
- §3.1 — insert — ambiguity — evidence payload always carries the union of both field groups, unused group null — serializers.py `evidence_out`
- §3.1 — revise — ambiguity — group presence/absence test precedes per-field type/enum checks; explicit null counts as absent — evidence.py:44
- §3.1 — revise — ambiguity — `sample_verified` on a `DESIGN_FACTOR` row is accepted and carried, not a group violation — evidence.py:81
- §3.1 — revise — ambiguity — `total_users`/`users_under_13` bounds check runs before the period rules — evidence.py:93
- §3.1 — revise — ambiguity — `ERR_INVALID_PERIOD` beats `ERR_SAMPLE_PERIOD_OVERLAP` — evidence.py:101
- §3.2 — insert — ambiguity — `posture_override` key is mandatory; omitting it → 422 (null is how override is cleared) — online_services.py:124
- §3.3 — revise — **mismatch** — `review_note` is a field of the shared status endpoint, applied on any accepted transition (not only `IN_REVIEW → REJECTED`); omission preserves the prior note — age_screens.py status handler
- §3.4 — revise — ambiguity — `content_keys` mandatory array, empty legal, unknown section name → 422 — notices.py:35
- §3.5 — insert — ambiguity — supersession leaves `revoked_at` (and other unearned stamps) null — helpers.py:115
- §3.5 — insert — ambiguity — grant evaluation order is body-shape `verification_evidence_code` → tier → email-plus → window — consents.py:136, consents.py:170
- §3.5 — revise — **mismatch** — a body `revocation_reason` is accepted then ignored; direct revoke always stores `PARENT_REFUSAL` — consents.py:205
- §3.6 — revise — **mismatch** — `activity_code` uniqueness is a naming discipline, not server-enforced; collection resolves the whitelist via `activity_id` — activities.py:19
- §3.6 — revise — ambiguity — whitelist is a mandatory array of legal data-element codes, possibly empty — activities.py:19
- §3.7 — insert — **mismatch** — `audit_note` applies on any accepted transition incl. approvals and blocks; disclosure-loss cascade leaves it untouched while escalation overwrites it — integrations.py:89, helpers.py `force_reaudit_on_escalation`
- §3.7 — insert — ambiguity — approval clause order is posture-frozen → behavioural-ad tier → disclosure — integrations.py:77-87
- §3.7 — revise — **mismatch** — `BLOCKED` is terminal (409 `ERR_INVALID_STATE`); the six accepted transitions enumerated — integrations.py:21
- §3.8 — revise — **mismatch** — step 8 precedes step 9, so a `scope_mode`-less fulfilment from `SUBMITTED` reports 422 `ERR_INVALID_REQUEST`, not 409 — rights.py:134
- §3.8 — insert — ambiguity — refusal/delete consent revocation only fires while the consent stands at `GRANTED`; the "all records disposed" test is vacuously true for an empty scope — rights.py:201, rights.py:217
- §3.9 — insert — ambiguity — within the shared 422 stage, range test then `retention_days` floor precede the disposal-method check — retention.py:56
- §3.9 — insert — ambiguity — a compliance run's `data` is exactly the seven summary fields; no `id`, timestamps or `version`, never listed or re-read — compliance_runs.py:22
- §3.10 — revise — ambiguity — `findings_open_count` is a body-shape check firing ahead of transition legality (422 not 409) — safe_harbor.py:141
- §3.10 — revise — ambiguity — a `FAILED` attempt before the remediation loop closes → 409 `ERR_INVALID_STATE` — safe_harbor.py:178

Both supplied hints were verified independently against the implementation and both held; each is now pinned (§3.3, §3.8). Beyond them the scan turned up 7 outright prose-vs-impl contradictions, the largest being §2.6's blanket version-bump claim and §3.7's "neither `APPROVED` nor `BLOCKED` is terminal". All pinned behaviours were exercised live against `python3 app.py` (register, age-screen transitions, posture, body-FK 422, BLOCKED terminality, evidence group ordering, retention 422 ordering, premature assessment FAILED, pagination and filter edge cases) and matched the prose written.

---

**PIPELINE COMPLETE.** Step 9 has written `workspace/PRD_COMPLETED.md`. Final artifact state:
SCAFFOLD trio + PRD.md + PRD_FINALIZED.md + PRD_COMPLETED.md + test_helpers/ + test_suite/
(17 files, 120 tests) + workspace/implementation/ (14 route modules + start.sh), with
results.{1..8}.json all recording 120/120.
