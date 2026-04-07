export const CONSTANTS = {
  auth: {
    ROLES: ['SellerAdmin', 'SellerAR', 'BuyerAP', 'Auditor', 'System'] as const
  }
} as const;

export type Role = typeof CONSTANTS.auth.ROLES[number];

export const DEFAULT_ROLE: Role = 'SellerAdmin';

export const DEFAULT_CURRENCY = 'USD';
