import {
  postAs,
  getAs,
  patchWithVersion,
} from '../../../test-helpers/api-client';
import {
  expectSuccess,
  expectClientError,
  expectErrorCode,
  expectErrorCodeOneOf,
} from '../../../test-helpers/assertions';
import {
  createEventOpen,
  createPackage,
  createSponsor,
  createApplication,
  submitApplication,
  approveApplication,
  countersignCommitment,
  transitionCommitment,
  getPackage,
  getEvent,
  getCommitment,
  getSponsor,
  updateEvent,
  updateSponsor,
  createClaim,
  finalizeClaim,
  voidClaim,
  transitionClaim,
  createActiveCommitmentVettedGold,
  createPendingCommitmentProspectGold,
  createActiveWithFinalizedLeads,
  createActiveWithFinalizedSpotlight,
  createTwoFinalizedSpotlightsEventFull,
  unwrap,
  uniqueId,
} from '../../../test-helpers/resources';
import { ERROR_CODES } from '../../../test-helpers/constants';

describe('Feature 6: Claim, Benefit Accounting, Spotlight Capacity Tests', () => {

  test('CLAIM_001: Creating a claim records intent as PROPOSED; benefits_left unchanged', async () => {

    const fixture = await createActiveCommitmentVettedGold();

    const commitmentBefore = await getCommitment(fixture.event.id, fixture.commitment.id);
    expect(commitmentBefore.benefits_left.LEAD_SCANS).toBe(100);

    const res = await postAs(
      `/events/${fixture.event.id}/commitments/${fixture.commitment.id}/claims`,
      { benefit_kind: 'LEAD_SCANS', quantity: 25 }
    );

    expectSuccess(res);

    const commitment = await getCommitment(fixture.event.id, fixture.commitment.id);
    const proposedClaim = commitment.claims.find(c => c.status === 'PROPOSED' && c.benefit_kind === 'LEAD_SCANS');
    expect(proposedClaim).toBeDefined();
    expect(proposedClaim!.quantity).toBe(25);
    expect(commitment.benefits_left.LEAD_SCANS).toBe(100);
  });

  test('CLAIM_002: Finalizing a claim decrements benefits_left', async () => {

    const fixture = await createActiveCommitmentVettedGold();
    const claim = await createClaim(fixture.event.id, fixture.commitment.id, {
      benefit_kind: 'LEAD_SCANS',
      quantity: 25,
    });

    const res = await transitionClaim(fixture.event.id, fixture.commitment.id, claim.id, 'FINALIZE');

    expectSuccess(res);

    const commitment = await getCommitment(fixture.event.id, fixture.commitment.id);
    const finalizedClaim = commitment.claims.find(c => c.id === claim.id);
    expect(finalizedClaim).toBeDefined();
    expect(finalizedClaim!.status).toBe('FINALIZED');
    expect(commitment.benefits_left.LEAD_SCANS).toBe(75);
  });

  test('CLAIM_003: Double finalize on already FINALIZED claim fails with ERR_INVALID_STATE', async () => {

    const fixture = await createActiveCommitmentVettedGold();
    const claim = await createClaim(fixture.event.id, fixture.commitment.id, {
      benefit_kind: 'LEAD_SCANS',
      quantity: 25,
    });
    await finalizeClaim(fixture.event.id, fixture.commitment.id, claim.id);

    const commitmentAfterFirst = await getCommitment(fixture.event.id, fixture.commitment.id);
    expect(commitmentAfterFirst.benefits_left.LEAD_SCANS).toBe(75);

    const res = await transitionClaim(fixture.event.id, fixture.commitment.id, claim.id, 'FINALIZE');

    await expectErrorCode(res, ERROR_CODES.INVALID_STATE);

    const commitment = await getCommitment(fixture.event.id, fixture.commitment.id);
    const finalizedClaim = commitment.claims.find(c => c.id === claim.id);
    expect(finalizedClaim!.status).toBe('FINALIZED');
    expect(commitment.benefits_left.LEAD_SCANS).toBe(75);
  });

  test('CLAIM_004: Voiding a PROPOSED claim marks it voided without restoring benefits', async () => {

    const fixture = await createActiveCommitmentVettedGold();
    const claim = await createClaim(fixture.event.id, fixture.commitment.id, {
      benefit_kind: 'LEAD_SCANS',
      quantity: 25,
    });

    const commitmentBefore = await getCommitment(fixture.event.id, fixture.commitment.id);
    expect(commitmentBefore.benefits_left.LEAD_SCANS).toBe(100);

    const res = await transitionClaim(fixture.event.id, fixture.commitment.id, claim.id, 'VOID');

    expectSuccess(res);

    const commitment = await getCommitment(fixture.event.id, fixture.commitment.id);
    const voidedClaim = commitment.claims.find(c => c.id === claim.id);
    expect(voidedClaim!.status).toBe('VOIDED');
    expect(commitment.benefits_left.LEAD_SCANS).toBe(100);
  });

  test('CLAIM_005: Voiding a FINALIZED claim restores benefits_left', async () => {

    const fixture = await createActiveWithFinalizedLeads();

    const commitmentBefore = await getCommitment(fixture.event.id, fixture.commitment.id);
    expect(commitmentBefore.benefits_left.LEAD_SCANS).toBe(70);

    const finalizedClaim = commitmentBefore.claims.find(c => c.status === 'FINALIZED');
    expect(finalizedClaim).toBeDefined();

    const res = await transitionClaim(fixture.event.id, fixture.commitment.id, finalizedClaim!.id, 'VOID');

    expectSuccess(res);

    const commitment = await getCommitment(fixture.event.id, fixture.commitment.id);
    expect(commitment.benefits_left.LEAD_SCANS).toBe(100);
  });

  test('CLAIM_006: Double void on already VOIDED claim fails with ERR_INVALID_STATE', async () => {

    const fixture = await createActiveWithFinalizedLeads();

    const commitmentBefore = await getCommitment(fixture.event.id, fixture.commitment.id);
    const finalizedClaim = commitmentBefore.claims.find(c => c.status === 'FINALIZED');
    expect(finalizedClaim).toBeDefined();
    await voidClaim(fixture.event.id, fixture.commitment.id, finalizedClaim!.id);

    const commitmentAfterVoid = await getCommitment(fixture.event.id, fixture.commitment.id);
    const voidedClaim = commitmentAfterVoid.claims.find(c => c.id === finalizedClaim!.id);
    expect(voidedClaim!.status).toBe('VOIDED');

    const res = await transitionClaim(fixture.event.id, fixture.commitment.id, finalizedClaim!.id, 'VOID');

    await expectErrorCode(res, ERROR_CODES.INVALID_STATE);

    const commitment = await getCommitment(fixture.event.id, fixture.commitment.id);
    const claimAfter = commitment.claims.find(c => c.id === finalizedClaim!.id);
    expect(claimAfter!.status).toBe('VOIDED');
  });

  test('CLAIM_007: Creating a STAGE_MINUTES claim records intent as PROPOSED', async () => {

    const fixture = await createActiveCommitmentVettedGold();

    const res = await postAs(
      `/events/${fixture.event.id}/commitments/${fixture.commitment.id}/claims`,
      { benefit_kind: 'STAGE_MINUTES', quantity: 20 }
    );

    expectSuccess(res);

    const commitment = await getCommitment(fixture.event.id, fixture.commitment.id);
    const proposedClaim = commitment.claims.find(c => c.status === 'PROPOSED' && c.benefit_kind === 'STAGE_MINUTES');
    expect(proposedClaim).toBeDefined();
    expect(proposedClaim!.quantity).toBe(20);

    expect(commitment.benefits_left.STAGE_MINUTES).toBe(30);
  });

  test('CLAIM_008: Finalizing a claim that exceeds remaining fails with ERR_INSUFFICIENT_BENEFIT', async () => {

    const fixture = await createActiveCommitmentVettedGold();

    const claim1 = await createClaim(fixture.event.id, fixture.commitment.id, {
      benefit_kind: 'STAGE_MINUTES',
      quantity: 30,
    });
    const claim2 = await createClaim(fixture.event.id, fixture.commitment.id, {
      benefit_kind: 'STAGE_MINUTES',
      quantity: 15,
    });

    await finalizeClaim(fixture.event.id, fixture.commitment.id, claim1.id);

    const commitmentAfterFirst = await getCommitment(fixture.event.id, fixture.commitment.id);
    expect(commitmentAfterFirst.benefits_left.STAGE_MINUTES).toBe(0);

    const res = await transitionClaim(fixture.event.id, fixture.commitment.id, claim2.id, 'FINALIZE');

    await expectErrorCode(res, ERROR_CODES.INSUFFICIENT_BENEFIT);

    const commitment = await getCommitment(fixture.event.id, fixture.commitment.id);
    const claimAfter = commitment.claims.find(c => c.id === claim2.id);
    expect(claimAfter!.status).toBe('PROPOSED');
    expect(commitment.benefits_left.STAGE_MINUTES).toBe(0);
  });

  test('CLAIM_009: Finalizing a claim that exactly matches remaining succeeds', async () => {

    const fixture = await createActiveCommitmentVettedGold();
    const claim = await createClaim(fixture.event.id, fixture.commitment.id, {
      benefit_kind: 'STAGE_MINUTES',
      quantity: 30,
    });

    const res = await transitionClaim(fixture.event.id, fixture.commitment.id, claim.id, 'FINALIZE');

    expectSuccess(res);

    const commitment = await getCommitment(fixture.event.id, fixture.commitment.id);
    expect(commitment.benefits_left.STAGE_MINUTES).toBe(0);
  });

  test('CLAIM_010: After consuming all, finalizing another claim fails with ERR_INSUFFICIENT_BENEFIT', async () => {

    const fixture = await createActiveCommitmentVettedGold();
    const claim1 = await createClaim(fixture.event.id, fixture.commitment.id, {
      benefit_kind: 'STAGE_MINUTES',
      quantity: 30,
    });
    const claim2 = await createClaim(fixture.event.id, fixture.commitment.id, {
      benefit_kind: 'STAGE_MINUTES',
      quantity: 1,
    });

    await finalizeClaim(fixture.event.id, fixture.commitment.id, claim1.id);

    const commitmentAfterFirst = await getCommitment(fixture.event.id, fixture.commitment.id);
    expect(commitmentAfterFirst.benefits_left.STAGE_MINUTES).toBe(0);

    const res = await transitionClaim(fixture.event.id, fixture.commitment.id, claim2.id, 'FINALIZE');

    await expectErrorCode(res, ERROR_CODES.INSUFFICIENT_BENEFIT);

    const commitment = await getCommitment(fixture.event.id, fixture.commitment.id);
    const claim2After = commitment.claims.find(c => c.id === claim2.id);
    expect(claim2After!.status).toBe('PROPOSED');
    expect(commitment.benefits_left.STAGE_MINUTES).toBe(0);
  });

  test('CLAIM_011: Creating a SPOTLIGHT claim is PROPOSED; event spotlight_slots_remaining unchanged', async () => {

    const fixture = await createActiveCommitmentVettedGold();

    const eventBefore = await getEvent(fixture.event.id);
    const spotlightBefore = eventBefore.spotlight_slots_remaining;

    const res = await postAs(
      `/events/${fixture.event.id}/commitments/${fixture.commitment.id}/claims`,
      { benefit_kind: 'SPOTLIGHT', quantity: 1 }
    );

    expectSuccess(res);

    const commitment = await getCommitment(fixture.event.id, fixture.commitment.id);
    const spotlightClaim = commitment.claims.find(c => c.benefit_kind === 'SPOTLIGHT' && c.status === 'PROPOSED');
    expect(spotlightClaim).toBeDefined();

    const eventAfter = await getEvent(fixture.event.id);
    expect(eventAfter.spotlight_slots_remaining).toBe(spotlightBefore);
  });

  test('CLAIM_012: Creating a SPOTLIGHT claim with quantity > 1 fails with ERR_BAD_REQUEST', async () => {

    const fixture = await createActiveCommitmentVettedGold();

    const res = await postAs(
      `/events/${fixture.event.id}/commitments/${fixture.commitment.id}/claims`,
      { benefit_kind: 'SPOTLIGHT', quantity: 2 }
    );

    await expectErrorCode(res, ERROR_CODES.BAD_REQUEST);

    const commitment = await getCommitment(fixture.event.id, fixture.commitment.id);
    const spotlightClaims = commitment.claims.filter(c => c.benefit_kind === 'SPOTLIGHT');
    expect(spotlightClaims.length).toBe(0);
  });

  test('CLAIM_013: Finalizing a SPOTLIGHT claim consumes event spotlight slot and commitment benefit', async () => {

    const fixture = await createActiveCommitmentVettedGold();
    const claim = await createClaim(fixture.event.id, fixture.commitment.id, {
      benefit_kind: 'SPOTLIGHT',
      quantity: 1,
    });

    const eventBefore = await getEvent(fixture.event.id);
    const spotlightBefore = eventBefore.spotlight_slots_remaining;

    const commitmentBefore = await getCommitment(fixture.event.id, fixture.commitment.id);
    expect(commitmentBefore.benefits_left.SPOTLIGHT).toBe(1);

    const res = await transitionClaim(fixture.event.id, fixture.commitment.id, claim.id, 'FINALIZE');

    expectSuccess(res);

    const commitment = await getCommitment(fixture.event.id, fixture.commitment.id);
    const finalizedClaim = commitment.claims.find(c => c.id === claim.id);
    expect(finalizedClaim!.status).toBe('FINALIZED');
    expect(commitment.benefits_left.SPOTLIGHT).toBe(0);

    const eventAfter = await getEvent(fixture.event.id);
    expect(eventAfter.spotlight_slots_remaining).toBe(spotlightBefore - 1);
  });

  test('CLAIM_014: Voiding a FINALIZED SPOTLIGHT claim restores commitment benefit and event slot', async () => {

    const fixture = await createActiveWithFinalizedSpotlight();

    const commitmentBefore = await getCommitment(fixture.event.id, fixture.commitment.id);
    expect(commitmentBefore.benefits_left.SPOTLIGHT).toBe(0);
    const eventBefore = await getEvent(fixture.event.id);
    const spotlightBefore = eventBefore.spotlight_slots_remaining;

    const spotlightClaim = commitmentBefore.claims.find(c => c.benefit_kind === 'SPOTLIGHT' && c.status === 'FINALIZED');
    expect(spotlightClaim).toBeDefined();

    const res = await transitionClaim(fixture.event.id, fixture.commitment.id, spotlightClaim!.id, 'VOID');

    expectSuccess(res);

    const commitment = await getCommitment(fixture.event.id, fixture.commitment.id);
    expect(commitment.benefits_left.SPOTLIGHT).toBe(1);

    const eventAfter = await getEvent(fixture.event.id);
    expect(eventAfter.spotlight_slots_remaining).toBe(spotlightBefore + 1);
  });

  test('CLAIM_015: Creating second non-voided SPOTLIGHT claim fails with ERR_DUPLICATE_CLAIM', async () => {

    const fixture = await createActiveCommitmentVettedGold();
    await createClaim(fixture.event.id, fixture.commitment.id, {
      benefit_kind: 'SPOTLIGHT',
      quantity: 1,
    });

    const res = await postAs(
      `/events/${fixture.event.id}/commitments/${fixture.commitment.id}/claims`,
      { benefit_kind: 'SPOTLIGHT', quantity: 1 }
    );

    await expectErrorCodeOneOf(res, [ERROR_CODES.DUPLICATE_CLAIM, ERROR_CODES.SPOTLIGHT_IN_USE]);
  });

  test('CLAIM_016: Creating SPOTLIGHT claim after voiding previous is allowed', async () => {

    const fixture = await createActiveCommitmentVettedGold();
    const claim = await createClaim(fixture.event.id, fixture.commitment.id, {
      benefit_kind: 'SPOTLIGHT',
      quantity: 1,
    });
    await voidClaim(fixture.event.id, fixture.commitment.id, claim.id);

    const res = await postAs(
      `/events/${fixture.event.id}/commitments/${fixture.commitment.id}/claims`,
      { benefit_kind: 'SPOTLIGHT', quantity: 1 }
    );

    expectSuccess(res);

    const commitment = await getCommitment(fixture.event.id, fixture.commitment.id);
    const proposedSpotlights = commitment.claims.filter(
      c => c.benefit_kind === 'SPOTLIGHT' && c.status === 'PROPOSED'
    );
    expect(proposedSpotlights.length).toBe(1);
  });

  test('CLAIM_017: Finalizing SPOTLIGHT when event is full fails with ERR_SPOTLIGHT_FULL', async () => {

    const fixture = await createTwoFinalizedSpotlightsEventFull();

    const eventFull = await getEvent(fixture.event.id);
    expect(eventFull.spotlight_slots_remaining).toBe(0);

    const pkg3 = await createPackage(fixture.event.id, {
      label: 'GOLD3',
      price_cents: 1,
      slot_count: 1,
      included_benefits: [{ benefit_kind: 'SPOTLIGHT', quantity: 1 }],
    });

    const sponsorC = await createSponsor(fixture.event.id, {
      display_name: 'C',
      legal_name: 'C LLC',
      primary_contact_email: 'c@c.test',
      status: 'VETTED',
    });

    const appC = await createApplication(fixture.event.id, {
      sponsor_id: sponsorC.id,
      package_id: pkg3.id,
    });
    await submitApplication(fixture.event.id, appC.id);
    let { commitment: commitmentC } = await approveApplication(fixture.event.id, appC.id);

    if (commitmentC.status !== 'ACTIVE') {
      commitmentC = await countersignCommitment(fixture.event.id, commitmentC.id);
    }

    const claimC = await createClaim(fixture.event.id, commitmentC.id, {
      benefit_kind: 'SPOTLIGHT',
      quantity: 1,
    });

    const res = await transitionClaim(fixture.event.id, commitmentC.id, claimC.id, 'FINALIZE');

    await expectErrorCode(res, ERROR_CODES.SPOTLIGHT_FULL);

    const commitment = await getCommitment(fixture.event.id, commitmentC.id);
    const claim = commitment.claims.find(c => c.id === claimC.id);
    expect(claim!.status).toBe('PROPOSED');

    const eventAfter = await getEvent(fixture.event.id);
    expect(eventAfter.spotlight_slots_remaining).toBe(0);
  });

  test('CLAIM_018: Decreasing spotlight_slot_count with only one finalized spotlight is allowed', async () => {

    const fixture = await createTwoFinalizedSpotlightsEventFull();

    const commitmentA = await getCommitment(fixture.event.id, fixture.commitmentA.id);
    const spotlightClaimA = commitmentA.claims.find(c => c.benefit_kind === 'SPOTLIGHT' && c.status === 'FINALIZED');
    expect(spotlightClaimA).toBeDefined();
    await voidClaim(fixture.event.id, fixture.commitmentA.id, spotlightClaimA!.id);

    const eventAfterVoid = await getEvent(fixture.event.id);
    expect(eventAfterVoid.spotlight_slots_remaining).toBe(1);

    const res = await patchWithVersion(
      `/events/${fixture.event.id}`,
      { spotlight_slot_count: 1 },
      eventAfterVoid.version
    );

    expectSuccess(res);

    const eventAfter = await getEvent(fixture.event.id);
    expect(eventAfter.spotlight_slot_count).toBe(1);
    expect(eventAfter.spotlight_slots_remaining).toBe(0);
  });

  test('CLAIM_019: Creating a claim with unknown benefit_kind fails with ERR_BAD_REQUEST', async () => {

    const fixture = await createActiveCommitmentVettedGold();

    const commitmentBefore = await getCommitment(fixture.event.id, fixture.commitment.id);
    const claimsCountBefore = commitmentBefore.claims.length;

    const res = await postAs(
      `/events/${fixture.event.id}/commitments/${fixture.commitment.id}/claims`,
      { benefit_kind: 'UNKNOWN_KIND', quantity: 1 }
    );

    await expectErrorCode(res, ERROR_CODES.BAD_REQUEST);

    const commitmentAfter = await getCommitment(fixture.event.id, fixture.commitment.id);
    expect(commitmentAfter.claims.length).toBe(claimsCountBefore);
  });

  test('CLAIM_020: Creating a claim with quantity=0 fails with ERR_BAD_REQUEST', async () => {

    const fixture = await createActiveCommitmentVettedGold();

    const commitmentBefore = await getCommitment(fixture.event.id, fixture.commitment.id);
    const claimsCountBefore = commitmentBefore.claims.length;

    const res = await postAs(
      `/events/${fixture.event.id}/commitments/${fixture.commitment.id}/claims`,
      { benefit_kind: 'LEAD_SCANS', quantity: 0 }
    );

    await expectErrorCode(res, ERROR_CODES.BAD_REQUEST);

    const commitmentAfter = await getCommitment(fixture.event.id, fixture.commitment.id);
    expect(commitmentAfter.claims.length).toBe(claimsCountBefore);
  });

  test('CLAIM_021: Creating a claim on PENDING_COUNTERSIGN commitment fails with ERR_COMMITMENT_NOT_ACTIVE', async () => {

    const fixture = await createPendingCommitmentProspectGold();

    const commitmentBefore = await getCommitment(fixture.event.id, fixture.commitment.id);
    expect(commitmentBefore.status).toBe('PENDING_COUNTERSIGN');
    const claimsCountBefore = commitmentBefore.claims.length;

    const res = await postAs(
      `/events/${fixture.event.id}/commitments/${fixture.commitment.id}/claims`,
      { benefit_kind: 'LEAD_SCANS', quantity: 1 }
    );

    await expectErrorCode(res, ERROR_CODES.COMMITMENT_NOT_ACTIVE);

    const commitmentAfter = await getCommitment(fixture.event.id, fixture.commitment.id);
    expect(commitmentAfter.claims.length).toBe(claimsCountBefore);
  });

  test('CLAIM_022: Creating a claim during LOCKDOWN fails with ERR_EVENT_LOCKDOWN', async () => {

    const fixture = await createActiveCommitmentVettedGold();

    const commitmentBefore = await getCommitment(fixture.event.id, fixture.commitment.id);
    const claimsCountBefore = commitmentBefore.claims.length;

    const event = await getEvent(fixture.event.id);
    const patchRes = await patchWithVersion(
      `/events/${fixture.event.id}`,
      { posture: 'LOCKDOWN' },
      event.version
    );
    expectSuccess(patchRes);

    const res = await postAs(
      `/events/${fixture.event.id}/commitments/${fixture.commitment.id}/claims`,
      { benefit_kind: 'LEAD_SCANS', quantity: 1 }
    );

    await expectErrorCode(res, ERROR_CODES.EVENT_LOCKDOWN);

    const commitmentAfter = await getCommitment(fixture.event.id, fixture.commitment.id);
    expect(commitmentAfter.claims.length).toBe(claimsCountBefore);
  });

  test('CLAIM_023: Voiding a claim during LOCKDOWN is allowed', async () => {

    const fixture = await createActiveWithFinalizedLeads();

    const event = await getEvent(fixture.event.id);
    const patchRes = await patchWithVersion(
      `/events/${fixture.event.id}`,
      { posture: 'LOCKDOWN' },
      event.version
    );
    expectSuccess(patchRes);

    const commitment = await getCommitment(fixture.event.id, fixture.commitment.id);
    const finalizedClaim = commitment.claims.find(c => c.status === 'FINALIZED');
    expect(finalizedClaim).toBeDefined();

    const res = await transitionClaim(fixture.event.id, fixture.commitment.id, finalizedClaim!.id, 'VOID');

    expectSuccess(res);

    const commitmentAfter = await getCommitment(fixture.event.id, fixture.commitment.id);

    const voidedClaim = commitmentAfter.claims.find(c => c.id === finalizedClaim!.id);
    expect(voidedClaim!.status).toBe('VOIDED');
    expect(commitmentAfter.benefits_left.LEAD_SCANS).toBe(100);
  });

  test('CLAIM_024: Finalizing a claim during LOCKDOWN fails with ERR_EVENT_LOCKDOWN', async () => {

    const fixture = await createActiveCommitmentVettedGold();
    const claim = await createClaim(fixture.event.id, fixture.commitment.id, {
      benefit_kind: 'LEAD_SCANS',
      quantity: 10,
    });

    const event = await getEvent(fixture.event.id);
    const patchRes = await patchWithVersion(
      `/events/${fixture.event.id}`,
      { posture: 'LOCKDOWN' },
      event.version
    );
    expectSuccess(patchRes);

    const res = await transitionClaim(fixture.event.id, fixture.commitment.id, claim.id, 'FINALIZE');

    await expectErrorCode(res, ERROR_CODES.EVENT_LOCKDOWN);

    const commitment = await getCommitment(fixture.event.id, fixture.commitment.id);
    const claimAfter = commitment.claims.find(c => c.id === claim.id);
    expect(claimAfter!.status).toBe('PROPOSED');
  });

  test('CLAIM_025: Voiding a claim during ARCHIVED is allowed (paperwork correction)', async () => {

    const fixture = await createActiveWithFinalizedLeads();

    const event = await getEvent(fixture.event.id);
    const patchRes = await patchWithVersion(
      `/events/${fixture.event.id}`,
      { posture: 'ARCHIVED' },
      event.version
    );
    expectSuccess(patchRes);

    const commitment = await getCommitment(fixture.event.id, fixture.commitment.id);
    const finalizedClaim = commitment.claims.find(c => c.status === 'FINALIZED');
    expect(finalizedClaim).toBeDefined();
    expect(commitment.benefits_left.LEAD_SCANS).toBe(70);

    const res = await transitionClaim(fixture.event.id, fixture.commitment.id, finalizedClaim!.id, 'VOID');

    expectSuccess(res);

    const commitmentAfter = await getCommitment(fixture.event.id, fixture.commitment.id);
    const voidedClaim = commitmentAfter.claims.find(c => c.id === finalizedClaim!.id);
    expect(voidedClaim!.status).toBe('VOIDED');
    expect(commitmentAfter.benefits_left.LEAD_SCANS).toBe(100);
  });

  test('CLAIM_026: Finalizing a claim for exactly all remaining benefits succeeds', async () => {

    const fixture = await createActiveCommitmentVettedGold();
    const claim = await createClaim(fixture.event.id, fixture.commitment.id, {
      benefit_kind: 'LEAD_SCANS',
      quantity: 100,
    });

    const res = await transitionClaim(fixture.event.id, fixture.commitment.id, claim.id, 'FINALIZE');

    expectSuccess(res);

    const commitment = await getCommitment(fixture.event.id, fixture.commitment.id);
    expect(commitment.benefits_left.LEAD_SCANS).toBe(0);
  });

  test('CLAIM_027: Finalizing a claim for more than remaining fails with ERR_INSUFFICIENT_BENEFIT', async () => {

    const fixture = await createActiveCommitmentVettedGold();

    const claim1 = await createClaim(fixture.event.id, fixture.commitment.id, {
      benefit_kind: 'LEAD_SCANS',
      quantity: 99,
    });
    await finalizeClaim(fixture.event.id, fixture.commitment.id, claim1.id);

    const commitmentAfterFirst = await getCommitment(fixture.event.id, fixture.commitment.id);
    expect(commitmentAfterFirst.benefits_left.LEAD_SCANS).toBe(1);

    const claim2 = await createClaim(fixture.event.id, fixture.commitment.id, {
      benefit_kind: 'LEAD_SCANS',
      quantity: 2,
    });

    const res = await transitionClaim(fixture.event.id, fixture.commitment.id, claim2.id, 'FINALIZE');

    await expectErrorCode(res, ERROR_CODES.INSUFFICIENT_BENEFIT);

    const commitment = await getCommitment(fixture.event.id, fixture.commitment.id);
    expect(commitment.benefits_left.LEAD_SCANS).toBe(1);
  });

  test('CLAIM_028: After partial consumption, proposing within remaining is allowed', async () => {

    const fixture = await createActiveCommitmentVettedGold();
    const claim1 = await createClaim(fixture.event.id, fixture.commitment.id, {
      benefit_kind: 'LEAD_SCANS',
      quantity: 60,
    });
    await finalizeClaim(fixture.event.id, fixture.commitment.id, claim1.id);

    const commitmentAfterFirst = await getCommitment(fixture.event.id, fixture.commitment.id);
    expect(commitmentAfterFirst.benefits_left.LEAD_SCANS).toBe(40);

    const res = await postAs(
      `/events/${fixture.event.id}/commitments/${fixture.commitment.id}/claims`,
      { benefit_kind: 'LEAD_SCANS', quantity: 30 }
    );

    expectSuccess(res);

    const commitment = await getCommitment(fixture.event.id, fixture.commitment.id);
    expect(commitment.benefits_left.LEAD_SCANS).toBe(40);
    const newProposed = commitment.claims.find(
      c => c.status === 'PROPOSED' && c.benefit_kind === 'LEAD_SCANS' && c.quantity === 30
    );
    expect(newProposed).toBeDefined();
  });

  test('CLAIM_029: Finalizing second claim that exceeds remaining fails', async () => {

    const fixture = await createActiveCommitmentVettedGold();

    const claim1 = await createClaim(fixture.event.id, fixture.commitment.id, {
      benefit_kind: 'LEAD_SCANS',
      quantity: 60,
    });
    const claim2 = await createClaim(fixture.event.id, fixture.commitment.id, {
      benefit_kind: 'LEAD_SCANS',
      quantity: 50,
    });

    await finalizeClaim(fixture.event.id, fixture.commitment.id, claim1.id);

    const commitmentAfterFirst = await getCommitment(fixture.event.id, fixture.commitment.id);
    expect(commitmentAfterFirst.benefits_left.LEAD_SCANS).toBe(40);

    const res = await transitionClaim(fixture.event.id, fixture.commitment.id, claim2.id, 'FINALIZE');

    await expectErrorCode(res, ERROR_CODES.INSUFFICIENT_BENEFIT);

    const commitment = await getCommitment(fixture.event.id, fixture.commitment.id);
    const claim2After = commitment.claims.find(c => c.id === claim2.id);
    expect(claim2After!.status).toBe('PROPOSED');
    expect(commitment.benefits_left.LEAD_SCANS).toBe(40);
  });

  test('CLAIM_030: Voiding a finalized claim restores benefits_left correctly', async () => {

    const fixture = await createActiveCommitmentVettedGold();
    const claim = await createClaim(fixture.event.id, fixture.commitment.id, {
      benefit_kind: 'LEAD_SCANS',
      quantity: 60,
    });
    await finalizeClaim(fixture.event.id, fixture.commitment.id, claim.id);

    const commitmentAfterFinalize = await getCommitment(fixture.event.id, fixture.commitment.id);
    expect(commitmentAfterFinalize.benefits_left.LEAD_SCANS).toBe(40);

    await voidClaim(fixture.event.id, fixture.commitment.id, claim.id);

    const commitment = await getCommitment(fixture.event.id, fixture.commitment.id);

    expect(commitment.benefits_left.LEAD_SCANS).toBe(100);
  });

  test('CLAIM_031: Finalizing claim when sponsor is WATCHLIST fails with ERR_COMMITMENT_NOT_ACTIVE', async () => {

    const fixture = await createActiveCommitmentVettedGold();
    const claim = await createClaim(fixture.event.id, fixture.commitment.id, {
      benefit_kind: 'LEAD_SCANS',
      quantity: 10,
    });

    const sponsor = await getSponsor(fixture.event.id, fixture.sponsor.id);
    await patchWithVersion(
      `/events/${fixture.event.id}/sponsors/${fixture.sponsor.id}`,
      { status: 'WATCHLIST' },
      sponsor.version
    );

    const commitmentSuspended = await getCommitment(fixture.event.id, fixture.commitment.id);
    expect(commitmentSuspended.status).toBe('SUSPENDED');

    const res = await transitionClaim(fixture.event.id, fixture.commitment.id, claim.id, 'FINALIZE');

    await expectErrorCode(res, ERROR_CODES.COMMITMENT_NOT_ACTIVE);

    const commitment = await getCommitment(fixture.event.id, fixture.commitment.id);
    const claimAfter = commitment.claims.find(c => c.id === claim.id);
    expect(claimAfter!.status).toBe('PROPOSED');
  });

  test('CLAIM_032: Blocking sponsor cascades to rescind commitment and void claims', async () => {

    const fixture = await createActiveCommitmentVettedGold();
    const claim = await createClaim(fixture.event.id, fixture.commitment.id, {
      benefit_kind: 'LEAD_SCANS',
      quantity: 10,
    });

    const commitmentBefore = await getCommitment(fixture.event.id, fixture.commitment.id);
    const claimBefore = commitmentBefore.claims.find(c => c.id === claim.id);
    expect(claimBefore!.status).toBe('PROPOSED');

    const sponsor = await getSponsor(fixture.event.id, fixture.sponsor.id);
    const res = await patchWithVersion(
      `/events/${fixture.event.id}/sponsors/${fixture.sponsor.id}`,
      { status: 'BLOCKED' },
      sponsor.version
    );

    expectSuccess(res);

    const commitment = await getCommitment(fixture.event.id, fixture.commitment.id);
    expect(commitment.status).toBe('RESCINDED');
    const claimAfter = commitment.claims.find(c => c.id === claim.id);
    expect(claimAfter!.status).toBe('VOIDED');
  });

  test('CLAIM_033: Event shows spotlight_slots_remaining=0 when all slots consumed', async () => {

    const fixture = await createTwoFinalizedSpotlightsEventFull();

    const event = await getEvent(fixture.event.id);

    expect(event.spotlight_slots_remaining).toBe(0);
  });

  test('CLAIM_034: Increasing spotlight_slot_count increases spotlight_slots_remaining', async () => {

    const fixture = await createTwoFinalizedSpotlightsEventFull();

    const eventBefore = await getEvent(fixture.event.id);
    expect(eventBefore.spotlight_slots_remaining).toBe(0);

    const res = await patchWithVersion(
      `/events/${fixture.event.id}`,
      { spotlight_slot_count: 3 },
      eventBefore.version
    );

    expectSuccess(res);

    const event = await getEvent(fixture.event.id);
    expect(event.spotlight_slot_count).toBe(3);
    expect(event.spotlight_slots_remaining).toBe(1);
  });

  test('CLAIM_035: Finalizing SPOTLIGHT on event with single slot consumes it', async () => {

    const event = await createEventOpen(uniqueId('SingleSpotlight'), 1);

    const pkg = await createPackage(event.id, {
      label: 'GOLD',
      price_cents: 1,
      slot_count: 1,
      included_benefits: [{ benefit_kind: 'SPOTLIGHT', quantity: 1 }],
    });

    const sponsor = await createSponsor(event.id, {
      display_name: 'S',
      legal_name: 'S LLC',
      primary_contact_email: 's@s.test',
      status: 'VETTED',
    });

    const app = await createApplication(event.id, {
      sponsor_id: sponsor.id,
      package_id: pkg.id,
    });
    await submitApplication(event.id, app.id);
    const { commitment } = await approveApplication(event.id, app.id);

    const claim = await createClaim(event.id, commitment.id, {
      benefit_kind: 'SPOTLIGHT',
      quantity: 1,
    });

    const eventBefore = await getEvent(event.id);
    expect(eventBefore.spotlight_slots_remaining).toBe(1);

    const res = await transitionClaim(event.id, commitment.id, claim.id, 'FINALIZE');

    expectSuccess(res);

    const eventAfter = await getEvent(event.id);
    expect(eventAfter.spotlight_slots_remaining).toBe(0);
  });

  test('CLAIM_036: Second sponsor cannot finalize SPOTLIGHT when event has only one slot', async () => {

    const event = await createEventOpen(uniqueId('OneSlotTwoSponsors'), 1);

    const pkg = await createPackage(event.id, {
      label: 'GOLD',
      price_cents: 1,
      slot_count: 2,
      included_benefits: [{ benefit_kind: 'SPOTLIGHT', quantity: 1 }],
    });

    const sponsor1 = await createSponsor(event.id, {
      display_name: 'S1',
      legal_name: 'S1 LLC',
      primary_contact_email: 's1@s.test',
      status: 'VETTED',
    });

    const sponsor2 = await createSponsor(event.id, {
      display_name: 'S2',
      legal_name: 'S2 LLC',
      primary_contact_email: 's2@s.test',
      status: 'VETTED',
    });

    const app1 = await createApplication(event.id, { sponsor_id: sponsor1.id, package_id: pkg.id });
    await submitApplication(event.id, app1.id);
    const { commitment: commitment1 } = await approveApplication(event.id, app1.id);

    const app2 = await createApplication(event.id, { sponsor_id: sponsor2.id, package_id: pkg.id });
    await submitApplication(event.id, app2.id);
    const { commitment: commitment2 } = await approveApplication(event.id, app2.id);

    const claim1 = await createClaim(event.id, commitment1.id, { benefit_kind: 'SPOTLIGHT', quantity: 1 });
    await finalizeClaim(event.id, commitment1.id, claim1.id);

    const eventFull = await getEvent(event.id);
    expect(eventFull.spotlight_slots_remaining).toBe(0);

    const claim2 = await createClaim(event.id, commitment2.id, { benefit_kind: 'SPOTLIGHT', quantity: 1 });

    const res = await transitionClaim(event.id, commitment2.id, claim2.id, 'FINALIZE');

    await expectErrorCode(res, ERROR_CODES.SPOTLIGHT_FULL);

    const commitment = await getCommitment(event.id, commitment2.id);
    const claim2After = commitment.claims.find(c => c.id === claim2.id);
    expect(claim2After!.status).toBe('PROPOSED');
  });

  test('CLAIM_037: Voiding SPOTLIGHT claim during LOCKDOWN is allowed and restores slot', async () => {

    const fixture = await createActiveWithFinalizedSpotlight();

    const event = await getEvent(fixture.event.id);
    const patchRes = await patchWithVersion(
      `/events/${fixture.event.id}`,
      { posture: 'LOCKDOWN' },
      event.version
    );
    expectSuccess(patchRes);

    const commitment = await getCommitment(fixture.event.id, fixture.commitment.id);
    const spotlightClaim = commitment.claims.find(c => c.benefit_kind === 'SPOTLIGHT' && c.status === 'FINALIZED');
    expect(spotlightClaim).toBeDefined();

    expect(commitment.benefits_left.SPOTLIGHT).toBe(0);

    const eventBefore = await getEvent(fixture.event.id);
    const slotsBefore = eventBefore.spotlight_slots_remaining;

    const res = await transitionClaim(fixture.event.id, fixture.commitment.id, spotlightClaim!.id, 'VOID');

    expectSuccess(res);

    const commitmentAfter = await getCommitment(fixture.event.id, fixture.commitment.id);
    const voidedClaim = commitmentAfter.claims.find(c => c.id === spotlightClaim!.id);
    expect(voidedClaim!.status).toBe('VOIDED');
    expect(commitmentAfter.benefits_left.SPOTLIGHT).toBe(1);

    const eventAfter = await getEvent(fixture.event.id);
    expect(eventAfter.spotlight_slots_remaining).toBe(slotsBefore + 1);
  });

  test('CLAIM_038: Voiding PROPOSED SPOTLIGHT claim does not affect event slots', async () => {

    const fixture = await createActiveCommitmentVettedGold();
    const claim = await createClaim(fixture.event.id, fixture.commitment.id, {
      benefit_kind: 'SPOTLIGHT',
      quantity: 1,
    });

    const eventBefore = await getEvent(fixture.event.id);
    const slotsBefore = eventBefore.spotlight_slots_remaining;
    const commitmentBefore = await getCommitment(fixture.event.id, fixture.commitment.id);
    expect(commitmentBefore.benefits_left.SPOTLIGHT).toBe(1);

    const res = await transitionClaim(fixture.event.id, fixture.commitment.id, claim.id, 'VOID');

    expectSuccess(res);

    const commitment = await getCommitment(fixture.event.id, fixture.commitment.id);
    const voidedClaim = commitment.claims.find(c => c.id === claim.id);
    expect(voidedClaim!.status).toBe('VOIDED');
    expect(commitment.benefits_left.SPOTLIGHT).toBe(1);

    const eventAfter = await getEvent(fixture.event.id);
    expect(eventAfter.spotlight_slots_remaining).toBe(slotsBefore);
  });

  test('CLAIM_039: Commitment claims list includes PROPOSED claim', async () => {

    const fixture = await createActiveCommitmentVettedGold();

    const res = await postAs(
      `/events/${fixture.event.id}/commitments/${fixture.commitment.id}/claims`,
      { benefit_kind: 'LEAD_SCANS', quantity: 25 }
    );

    expectSuccess(res);

    const commitment = await getCommitment(fixture.event.id, fixture.commitment.id);
    const proposedClaims = commitment.claims.filter(
      c => c.status === 'PROPOSED' && c.benefit_kind === 'LEAD_SCANS'
    );
    expect(proposedClaims.length).toBe(1);
    expect(proposedClaims[0].quantity).toBe(25);
  });

  test('CLAIM_040: Blocking sponsor with PROPOSED claim voids claim and releases slot', async () => {

    const fixture = await createActiveCommitmentVettedGold();
    const claim = await createClaim(fixture.event.id, fixture.commitment.id, {
      benefit_kind: 'LEAD_SCANS',
      quantity: 25,
    });

    const pkgBefore = await getPackage(fixture.event.id, fixture.gold.id);
    expect(pkgBefore.slots_remaining).toBe(0);

    const sponsor = await getSponsor(fixture.event.id, fixture.sponsor.id);
    const res = await patchWithVersion(
      `/events/${fixture.event.id}/sponsors/${fixture.sponsor.id}`,
      { status: 'BLOCKED' },
      sponsor.version
    );

    expectSuccess(res);

    const commitment = await getCommitment(fixture.event.id, fixture.commitment.id);
    expect(commitment.status).toBe('RESCINDED');

    const claimAfter = commitment.claims.find(c => c.id === claim.id);
    expect(claimAfter!.status).toBe('VOIDED');

    const pkg = await getPackage(fixture.event.id, fixture.gold.id);
    expect(pkg.slots_remaining).toBe(1);
  });

});
