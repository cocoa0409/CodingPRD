import axios, { AxiosResponse } from 'axios';
import {
  ApiResponse,
  Journal,
  CreateJournalPayload,
  Manuscript,
  CreateManuscriptPayload,
  UpdateManuscriptPayload,
  ReviewAssignment,
  CreateReviewAssignmentPayload,
  Review,
  ReviewInvitationPayload,
  ReviewerProfile,
  CreateReviewerProfilePayload,
  AddCertificationPayload,
  Certification,
  ConflictOfInterest,
  CreateConflictOfInterestPayload,
  UserRole,
} from './types';

export const BASE_URL = process.env.API_URL ?? 'http://localhost:3000';

export async function makeRequest<
  TRes,
  TReq = unknown
>(
  method: string,
  path: string,
  paramsOrData?: TReq | Record<string, unknown>,
  headers: Record<string, string> = {}
): Promise<AxiosResponse<ApiResponse<TRes>>> {
  const config: Record<string, unknown> = {
    method,
    url: `${BASE_URL}${path}`,
    headers,
    validateStatus: () => true,
  };

  if (paramsOrData !== undefined) {
    if (['GET', 'get', 'DELETE', 'delete'].includes(method as string)) {
      (config as any).params = paramsOrData;
    } else {
      (config as any).data = paramsOrData;
    }
  }

  return axios(config);
}

export interface ApiHeadersBase {
  'X-User-ID': string;
  'X-User-Role': UserRole;
  [key: string]: string;
}

export const apiClient = {
  createJournal: (payload: CreateJournalPayload, headers: ApiHeadersBase) =>
    makeRequest<Journal>('POST', '/journals', payload, headers),
  getJournals: (headers: ApiHeadersBase, params?: { limit?: number; offset?: number }) =>
    makeRequest<Journal[]>('GET', '/journals', params, headers),
  getJournal: (journalId: string, headers: ApiHeadersBase) =>
    makeRequest<Journal>('GET', `/journals/${journalId}`, undefined, headers),
  beginReview: (journalId: string, headers: ApiHeadersBase) =>
    makeRequest<Journal>('POST', `/journals/${journalId}/begin-review`, undefined, headers),
  initiatePublication: (journalId: string, headers: ApiHeadersBase) =>
    makeRequest<Journal>('POST', `/journals/${journalId}/initiate-publication`, undefined, headers),
  finalizePublication: (journalId: string, headers: ApiHeadersBase) =>
    makeRequest<any>('POST', `/journals/${journalId}/finalize-publication`, undefined, headers),

  createManuscript: (journalId: string, payload: CreateManuscriptPayload, headers: ApiHeadersBase) =>
    makeRequest<Manuscript>('POST', `/journals/${journalId}/manuscripts`, payload, headers),
  getManuscripts: (journalId: string, headers: ApiHeadersBase, params?: { limit?: number; offset?: number }) =>
    makeRequest<Manuscript[]>('GET', `/journals/${journalId}/manuscripts`, params, headers),
  getManuscript: (journalId: string, manuscriptId: string, headers: ApiHeadersBase) =>
    makeRequest<Manuscript>('GET', `/journals/${journalId}/manuscripts/${manuscriptId}`, undefined, headers),
  updateManuscript: (journalId: string, manuscriptId: string, payload: UpdateManuscriptPayload, headers: ApiHeadersBase) =>
    makeRequest<Manuscript>('PUT', `/journals/${journalId}/manuscripts/${manuscriptId}`, payload, headers),

  createReviewAssignment: (journalId: string, manuscriptId: string, payload: CreateReviewAssignmentPayload, headers: ApiHeadersBase) =>
    makeRequest<ReviewAssignment>('POST', `/journals/${journalId}/manuscripts/${manuscriptId}/review-assignments`, payload, headers),
  getReviewAssignments: (journalId: string, manuscriptId: string, headers: ApiHeadersBase, params?: { limit?: number; offset?: number }) =>
    makeRequest<ReviewAssignment[]>('GET', `/journals/${journalId}/manuscripts/${manuscriptId}/review-assignments`, params, headers),
  getReviewAssignment: (journalId: string, manuscriptId: string, assignmentId: string, headers: ApiHeadersBase) =>
    makeRequest<ReviewAssignment>('GET', `/journals/${journalId}/manuscripts/${manuscriptId}/review-assignments/${assignmentId}`, undefined, headers),
  cancelReviewAssignment: (journalId: string, manuscriptId: string, assignmentId: string, headers: ApiHeadersBase) =>
    makeRequest<ReviewAssignment>('POST', `/journals/${journalId}/manuscripts/${manuscriptId}/review-assignments/${assignmentId}/cancel`, undefined, headers),

  inviteReviewer: (journalId: string, payload: ReviewInvitationPayload, headers: ApiHeadersBase) =>
    makeRequest<Review>('POST', `/journals/${journalId}/reviews`, payload, headers),
  getReviews: (journalId: string, headers: ApiHeadersBase, params?: { limit?: number; offset?: number }) =>
    makeRequest<Review[]>('GET', `/journals/${journalId}/reviews`, params, headers),
  getReview: (journalId: string, reviewId: string, headers: ApiHeadersBase) =>
    makeRequest<Review>('GET', `/journals/${journalId}/reviews/${reviewId}`, undefined, headers),
  acceptReview: (journalId: string, reviewId: string, headers: ApiHeadersBase) =>
    makeRequest<Review>('POST', `/journals/${journalId}/reviews/${reviewId}/accept`, undefined, headers),
  declineReview: (journalId: string, reviewId: string, headers: ApiHeadersBase) =>
    makeRequest<Review>('POST', `/journals/${journalId}/reviews/${reviewId}/decline`, undefined, headers),
  submitReview: (journalId: string, reviewId: string, headers: ApiHeadersBase) =>
    makeRequest<Review>('POST', `/journals/${journalId}/reviews/${reviewId}/submit`, undefined, headers),
  cancelReview: (journalId: string, reviewId: string, headers: ApiHeadersBase) =>
    makeRequest<Review>('POST', `/journals/${journalId}/reviews/${reviewId}/cancel`, undefined, headers),

  createReviewerProfile: (journalId: string, payload: CreateReviewerProfilePayload, headers: ApiHeadersBase) =>
    makeRequest<ReviewerProfile>('POST', `/journals/${journalId}/reviewer-profiles`, payload, headers),
  getReviewerProfiles: (journalId: string, headers: ApiHeadersBase, params?: { limit?: number; offset?: number }) =>
    makeRequest<ReviewerProfile[]>('GET', `/journals/${journalId}/reviewer-profiles`, params, headers),
  getReviewerProfile: (journalId: string, reviewerId: string, headers: ApiHeadersBase) =>
    makeRequest<ReviewerProfile>('GET', `/journals/${journalId}/reviewer-profiles/${reviewerId}`, undefined, headers),
  addCertification: (journalId: string, reviewerId: string, payload: AddCertificationPayload, headers: ApiHeadersBase) =>
    makeRequest<Certification>('POST', `/journals/${journalId}/reviewer-profiles/${reviewerId}/certifications`, payload, headers),

  createConflictOfInterest: (journalId: string, payload: CreateConflictOfInterestPayload, headers: ApiHeadersBase) =>
    makeRequest<ConflictOfInterest>('POST', `/journals/${journalId}/conflicts-of-interest`, payload, headers),
  getConflictsOfInterest: (journalId: string, headers: ApiHeadersBase, params?: { limit?: number; offset?: number }) =>
    makeRequest<ConflictOfInterest[]>('GET', `/journals/${journalId}/conflicts-of-interest`, params, headers),
  getConflictOfInterest: (journalId: string, conflictId: string, headers: ApiHeadersBase) =>
    makeRequest<ConflictOfInterest>('GET', `/journals/${journalId}/conflicts-of-interest/${conflictId}`, undefined, headers),

} as const;
