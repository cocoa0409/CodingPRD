import {
  WorkspacePosture, MatterPosture,
  REVIEW_THRESHOLD_PERCENT
} from './constants';

export function calculateBytesAvailable(
  quotaBytes: number,
  bytesReserved: number,
  bytesStored: number
): number {
  return quotaBytes - bytesReserved - bytesStored;
}

export function wouldExceedQuota(
  quotaBytes: number,
  bytesReserved: number,
  bytesStored: number,
  additionalBytes: number
): boolean {
  return (bytesReserved + bytesStored + additionalBytes) > quotaBytes;
}

export function isBelowReviewThreshold(quotaBytes: number, bytesAvailable: number): boolean {
  const threshold = quotaBytes * REVIEW_THRESHOLD_PERCENT;
  return bytesAvailable < threshold;
}

export function calculateWorkspacePosture(
  hasFrozenMatter: boolean,
  quotaBytes: number,
  bytesAvailable: number
): WorkspacePosture {
  if (hasFrozenMatter) {
    return 'LOCKDOWN';
  }

  if (isBelowReviewThreshold(quotaBytes, bytesAvailable)) {
    return 'REVIEW';
  }

  return 'NORMAL';
}

export function calculateMatterPosture(
  hasActiveCourtOrderedHold: boolean,
  hasIssuedHold: boolean,
  hasInFlightCollection: boolean
): MatterPosture {
  if (hasActiveCourtOrderedHold) {
    return 'FROZEN';
  }

  if (hasIssuedHold || hasInFlightCollection) {
    return 'REVIEW';
  }

  return 'OPEN';
}

export function scopeCoversDataSource(
  scope: 'ALL_DATA' | 'EMAIL_ONLY' | 'CHAT_ONLY' | 'DRIVE_ONLY',
  dataSource: 'EMAIL' | 'CHAT' | 'DRIVE'
): boolean {
  if (scope === 'ALL_DATA') {
    return true;
  }

  const scopeToDataSource: Record<string, string> = {
    'EMAIL_ONLY': 'EMAIL',
    'CHAT_ONLY': 'CHAT',
    'DRIVE_ONLY': 'DRIVE',
  };

  return scopeToDataSource[scope] === dataSource;
}

export function isLegalBasisValidForMatterType(
  matterType: 'LITIGATION' | 'INVESTIGATION',
  legalBasis: 'LITIGATION' | 'REGULATORY' | 'CONTRACT',
  isCourtOrdered: boolean
): boolean {
  if (matterType === 'LITIGATION') {
    if (legalBasis === 'LITIGATION' || legalBasis === 'CONTRACT') {
      return true;
    }

    return legalBasis === 'REGULATORY' && isCourtOrdered;
  }

  if (matterType === 'INVESTIGATION') {
    if (legalBasis === 'REGULATORY' || legalBasis === 'CONTRACT') {
      return true;
    }

    return legalBasis === 'LITIGATION' && isCourtOrdered;
  }

  return false;
}

export function isCollectionInFlight(status: string): boolean {
  return ['SUBMITTED', 'APPROVED', 'IN_PROGRESS'].includes(status);
}

export function isHoldActiveObligation(status: string): boolean {
  return ['ISSUED', 'ACTIVE', 'SUSPENDED'].includes(status);
}

export function canWithdrawCollection(status: string): boolean {
  return status !== 'DELIVERED';
}
