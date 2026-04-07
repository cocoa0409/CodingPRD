import { Response } from 'supertest';
import {
  ErrorCode,
  CapacityScope,
  RESPONSE_TYPE,
  POSTURE,
  EPISODE_STATUS,
  CLEARANCE,
  RESERVATION_STATUS,
  DEAL_STATUS,
} from './constants';

export function expectSuccess(response: Response): void {
  expect(response.status).toBeGreaterThanOrEqual(200);
  expect(response.status).toBeLessThan(300);
  expect(response.body).toBeDefined();
  if ('response_type' in response.body) {
    expect(
      response.body.response_type === RESPONSE_TYPE.OBJECT ||
      response.body.response_type === RESPONSE_TYPE.ARRAY
    ).toBe(true);
  }
}

export function extractErrorCode(body: any): string | undefined {
  if (!body) return undefined;

  return (
    body.error_code ||
    body?.data?.error_code ||
    body?.data?.error_id ||
    body?.error?.code
  );
}

export function extractCapacityScope(body: any): string | undefined {
  if (!body) return undefined;
  return (
    body.capacity_scope ||
    body?.data?.capacity_scope
  );
}

export function expectError(response: Response, status: number, code?: string): void {
  expect(response.status).toBe(status);
  const resolvedCode = extractErrorCode(response.body);
  if (code) {
    expect(resolvedCode).toBe(code);
  } else {
    expect(resolvedCode).toBeDefined();
  }
}

export function expectErrorCode(response: Response, code: ErrorCode | string): void {
  expect(response.status).toBeGreaterThanOrEqual(400);
  expect(response.status).toBeLessThan(500);
  const resolvedCode = extractErrorCode(response.body);
  expect(resolvedCode).toBe(code);
}

export function expectCapacityExceeded(response: Response, scope: CapacityScope): void {
  expectErrorCode(response, 'ERR_CAPACITY_EXCEEDED');
  const resolvedScope = extractCapacityScope(response.body);
  expect(resolvedScope).toBe(scope);
}

export function expectStatusOneOf(response: Response, statuses: number[]): void {
  expect(statuses).toContain(response.status);
}

export function expectErrorCodeOneOf(response: Response, codes: (ErrorCode | string)[]): void {
  expect(response.status).toBeGreaterThanOrEqual(400);
  expect(response.status).toBeLessThan(500);
  const resolvedCode = extractErrorCode(response.body);
  expect(codes).toContain(resolvedCode);
}

export function expectResponseTypeError(response: Response): void {
  expect(response.body.response_type).toBe(RESPONSE_TYPE.ERROR);
}

export function expectResponseTypeObject(response: Response): void {
  expect(response.body.response_type).toBe(RESPONSE_TYPE.OBJECT);
}

export function expectPostureNormal(podcast: any): void {
  expect(podcast.posture).toBe(POSTURE.NORMAL);
}

export function expectPostureRestricted(podcast: any): void {
  expect(podcast.posture).toBe(POSTURE.RESTRICTED);
}

export function expectPodcastInventory(
  podcast: any,
  expected: {
    ad_held_seconds?: number;
    ad_committed_seconds?: number;
    ad_available_seconds?: number;
  }
): void {
  if (expected.ad_held_seconds !== undefined) {
    expect(podcast.ad_held_seconds).toBe(expected.ad_held_seconds);
  }
  if (expected.ad_committed_seconds !== undefined) {
    expect(podcast.ad_committed_seconds).toBe(expected.ad_committed_seconds);
  }
  if (expected.ad_available_seconds !== undefined) {
    expect(podcast.ad_available_seconds).toBe(expected.ad_available_seconds);
  }
}

export function expectOpenClaimCount(podcast: any, count: number): void {
  expect(podcast.open_claim_count).toBe(count);
}

export function expectOpsRunIndex(podcast: any, index: number): void {
  expect(podcast.ops_run_index).toBe(index);
}

export function expectEpisodeStatus(episode: any, status: string): void {
  expect(episode.status).toBe(status);
}

export function expectEpisodeClearance(episode: any, clearance: string): void {
  expect(episode.clearance).toBe(clearance);
}

export function expectEpisodeDraft(episode: any): void {
  expect(episode.status).toBe(EPISODE_STATUS.DRAFT);
}

export function expectEpisodeSubmitted(episode: any): void {
  expect(episode.status).toBe(EPISODE_STATUS.SUBMITTED);
}

export function expectEpisodeLive(episode: any): void {
  expect(episode.status).toBe(EPISODE_STATUS.LIVE);
}

export function expectEpisodeRetracted(episode: any): void {
  expect(episode.status).toBe(EPISODE_STATUS.RETRACTED);
}

export function expectEpisodeClear(episode: any): void {
  expect(episode.clearance).toBe(CLEARANCE.CLEAR);
}

export function expectEpisodeUnderReview(episode: any): void {
  expect(episode.clearance).toBe(CLEARANCE.UNDER_REVIEW);
}

export function expectEpisodeInventory(
  episode: any,
  expected: {
    ad_slots_total_seconds?: number;
    ad_slots_held_seconds?: number;
    ad_slots_committed_seconds?: number;
  }
): void {
  if (expected.ad_slots_total_seconds !== undefined) {
    expect(episode.ad_slots_total_seconds).toBe(expected.ad_slots_total_seconds);
  }
  if (expected.ad_slots_held_seconds !== undefined) {
    expect(episode.ad_slots_held_seconds).toBe(expected.ad_slots_held_seconds);
  }
  if (expected.ad_slots_committed_seconds !== undefined) {
    expect(episode.ad_slots_committed_seconds).toBe(expected.ad_slots_committed_seconds);
  }
}

export function expectDealStatus(deal: any, status: string): void {
  expect(deal.status).toBe(status);
}

export function expectDealActive(deal: any): void {
  expect(deal.status).toBe(DEAL_STATUS.ACTIVE);
}

export function expectDealPaused(deal: any): void {
  expect(deal.status).toBe(DEAL_STATUS.PAUSED);
}

export function expectDealClosed(deal: any): void {
  expect(deal.status).toBe(DEAL_STATUS.CLOSED);
}

export function expectScriptVersion(deal: any, version: number): void {
  expect(deal.script_version).toBe(version);
}

export function expectDealBudget(
  deal: any,
  expected: {
    budget_held_cents?: number;
    budget_committed_cents?: number;
    budget_spent_cents?: number;
    budget_available_cents?: number;
  }
): void {
  if (expected.budget_held_cents !== undefined) {
    expect(deal.budget_held_cents).toBe(expected.budget_held_cents);
  }
  if (expected.budget_committed_cents !== undefined) {
    expect(deal.budget_committed_cents).toBe(expected.budget_committed_cents);
  }
  if (expected.budget_spent_cents !== undefined) {
    expect(deal.budget_spent_cents).toBe(expected.budget_spent_cents);
  }
  if (expected.budget_available_cents !== undefined) {
    expect(deal.budget_available_cents).toBe(expected.budget_available_cents);
  }
}

export function expectReservationStatus(reservation: any, status: string): void {
  expect(reservation.status).toBe(status);
}

export function expectReservationHold(reservation: any): void {
  expect(reservation.status).toBe(RESERVATION_STATUS.HOLD);
}

export function expectReservationApproved(reservation: any): void {
  expect(reservation.status).toBe(RESERVATION_STATUS.APPROVED);
}

export function expectReservationNeedsReview(reservation: any): void {
  expect(reservation.status).toBe(RESERVATION_STATUS.NEEDS_REVIEW);
}

export function expectReservationOverbooked(reservation: any): void {
  expect(reservation.status).toBe(RESERVATION_STATUS.OVERBOOKED);
}

export function expectReservationSettled(reservation: any): void {
  expect(reservation.status).toBe(RESERVATION_STATUS.SETTLED);
}

export function expectReservationCredited(reservation: any): void {
  expect(reservation.status).toBe(RESERVATION_STATUS.CREDITED);
}

export function expectReservationCanceled(reservation: any): void {
  expect(reservation.status).toBe(RESERVATION_STATUS.CANCELED);
}

export function expectReservationExpired(reservation: any): void {
  expect(reservation.status).toBe(RESERVATION_STATUS.EXPIRED);
}

export function expectScriptVersionPinned(reservation: any, version: number): void {
  expect(reservation.script_version_pinned).toBe(version);
}

export function expectReservationInEpisode(
  episode: any,
  reservationId: string,
  expectedStatus: string
): void {
  const reservation = episode.reservations?.find((r: any) => r.id === reservationId);
  expect(reservation).toBeDefined();
  expect(reservation.status).toBe(expectedStatus);
}

export function expectVersionIncremented(current: number, previous: number): void {
  expect(current).toBeGreaterThan(previous);
}

export function expectVersionIncrementedBy(current: number, previous: number, increment: number = 1): void {
  expect(current).toBe(previous + increment);
}

export function expectIdempotentResponse(response1: Response, response2: Response): void {
  expectSuccess(response1);
  expectSuccess(response2);

  const data1 = response1.body.data ?? response1.body;
  const data2 = response2.body.data ?? response2.body;

  expect(data1).toEqual(data2);
}
